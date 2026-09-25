from collections.abc import Mapping, Sequence
from typing import Any

from aws_cdk import Stack
from aws_cdk.aws_ecs import Secret as EcsSecret
from aws_cdk.aws_ssm import IStringParameter, StringParameter
from aws_cdk.custom_resources import AwsCustomResource, AwsSdkCall, PhysicalResourceId
from constructs import Construct

from callsy_cdk.secure_parameter.role import get_role

# Value written at create. The real value is filled in by hand afterwards.
PLACEHOLDER = "-"

# Error the delete call tolerates, so a parameter removed by hand does not wedge a stack.
PARAMETER_NOT_FOUND = "ParameterNotFound"

# Error the create call tolerates when `ignore_existing` is set, so a parameter left behind
# by a rolled back stack does not block the next deploy.
PARAMETER_ALREADY_EXISTS = "ParameterAlreadyExists"


class SecureParameter(AwsCustomResource):
    """
    Creates one encrypted parameter in Parameter Store.
    The value is written once and later deploys leave it alone.
    The parameter is removed when the stack is deleted.
    """

    def __init__(
            self,
            scope: Stack,
            name: str,
            description: str,
            *,
            prefix: str,
            tags: Mapping[str, str] | None = None,
            placeholder: str = PLACEHOLDER,
            key_id: str | None = None,
            tier: str | None = None,
            ignore_existing: bool = False
    ) -> None:
        parameter_name = self.build_name(prefix=prefix, name=name)

        # Tag this custom resource with a project prefix (as the rest of the resources).
        parameter_tags = dict(tags) if tags is not None else {"Project": prefix}

        parameters: dict[str, Any] = {
            "Name": parameter_name,
            "Description": description,
            "Value": placeholder,
            "Type": "SecureString",
            # Never override the value as they are populated manually.
            "Overwrite": False,
            "Tags": [{"Key": key, "Value": value} for key, value in parameter_tags.items()]
        }

        # The account default key encrypts the parameter when no key is named.
        if key_id is not None: parameters["KeyId"] = key_id

        # One of `Standard`, `Advanced` or `Intelligent-Tiering`.
        if tier is not None: parameters["Tier"] = tier

        # SecureString is written through the SSM API.
        create_call = AwsSdkCall(
            service="SSM",
            action="putParameter",
            parameters=parameters,
            physical_resource_id=PhysicalResourceId.of(parameter_name),
            ignore_error_codes_matching=PARAMETER_ALREADY_EXISTS if ignore_existing else None
        )

        delete_call = AwsSdkCall(
            service="SSM",
            action="deleteParameter",
            parameters={"Name": parameter_name},
            # A parameter removed by hand must not wedge the stack.
            ignore_error_codes_matching=PARAMETER_NOT_FOUND
        )

        super().__init__(
            scope=scope,
            # A construct id can not hold the slash that separates the provider from the key.
            id=name.replace("/", ""),
            # No `update` call is given. A deploy must never rewrite a populated value.
            on_create=create_call,
            on_delete=delete_call,
            role=get_role(scope=scope, prefix=prefix),
            install_latest_aws_sdk=False
        )

        self.prefix = prefix
        self.parameter_name = parameter_name

    @staticmethod
    def build_name(prefix: str, name: str) -> str:
        """
        Returns the full name a parameter carries under one prefix.
        """
        return f"/{prefix}/{name}"

    @staticmethod
    def chain(parameters: Sequence["SecureParameter"]) -> None:
        """
        Makes each parameter wait for the one before it.
        Parameter Store throttles a burst of writes, so they are created one after another.
        """
        previous: SecureParameter | None = None

        for parameter in parameters:
            if previous is not None: parameter.node.add_dependency(previous)
            previous = parameter

    def as_string_parameter(self, scope: Construct, id: str | None = None) -> IStringParameter:
        """
        Returns the deployed parameter, read by whatever consumes it.
        The value is never resolved at synthesis.
        """
        return StringParameter.from_secure_string_parameter_attributes(
            scope=scope,
            id=id or f"{self.node.id}Parameter",
            parameter_name=self.parameter_name,
            # The full name holds a slash, so it is a path and not a simple name. Left
            # undetected, the rendered arn carries a doubled slash and matches nothing.
            simple_name=False
        )

    def as_ecs_secret(self, scope: Construct, id: str | None = None) -> EcsSecret:
        """
        Returns the container secret that reads this parameter.
        The container reads the value when it starts, never at synthesis.
        """
        return EcsSecret.from_ssm_parameter(self.as_string_parameter(scope=scope, id=id))
