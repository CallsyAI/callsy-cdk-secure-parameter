import re
from typing import cast

from aws_cdk import Stack
from aws_cdk.aws_iam import ManagedPolicy, PolicyStatement, Role, ServicePrincipal
from constructs import Construct

# Construct id of the role that every secure parameter of a stack shares.
ROLE_ID = "SecureParameterRole"

# Actions the role needs to create, tag and remove one parameter.
ROLE_ACTIONS = ["ssm:PutParameter", "ssm:AddTagsToResource", "ssm:DeleteParameter"]


def get_role(scope: Stack, prefix: str) -> Role:
    """
    Returns the role that writes every secure parameter of this stack.
    The role is built once and reused, and each new prefix widens its policy once.
    """
    existing = scope.node.try_find_child(ROLE_ID)
    role = cast(Role, existing) if existing is not None else _create_role(scope)

    _grant_prefix(scope=scope, role=role, prefix=prefix)

    return role


def _create_role(scope: Stack) -> Role:
    """
    Builds the role the custom resource assumes while it writes a parameter.
    """
    return Role(
        scope=scope,
        id=ROLE_ID,
        assumed_by=ServicePrincipal("lambda.amazonaws.com"),
        managed_policies=[
            ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        ]
    )


def _grant_prefix(scope: Stack, role: Role, prefix: str) -> None:
    """
    Grants the role every parameter under one prefix, and does so once per prefix.
    One grant covers the whole prefix because a grant per parameter races IAM propagation.
    """
    # An empty construct marks the prefix as granted. The stack tree is the one place that
    # outlives two parameters built far apart in the same synthesis.
    marker_id = f"{ROLE_ID}Grant{re.sub(r'[^A-Za-z0-9]', '', prefix)}"

    if scope.node.try_find_child(marker_id) is not None: return

    Construct(scope=scope, id=marker_id)

    role.add_to_policy(
        PolicyStatement(
            actions=ROLE_ACTIONS,
            resources=[
                scope.format_arn(
                    service="ssm",
                    resource="parameter",
                    resource_name=f"{prefix}/*"
                )
            ]
        )
    )
