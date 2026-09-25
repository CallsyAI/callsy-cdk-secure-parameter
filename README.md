# callsy-cdk-secure-parameter

An AWS CDK construct that creates an encrypted SSM SecureString parameter, writes a placeholder into it once, and then never touches the value again. Populate it by hand, redeploy as often as you like, and the secret stays where you put it.

## Features

- **Write-once semantics** — the parameter is created with a placeholder and has no update call. A later deploy can never rewrite a value you filled in by hand.
- **Secrets never touch your repository** — no value passes through the codebase, through git, or through a CloudFormation template.
- **Encrypted at rest** — every parameter is a `SecureString`, encrypted with the account default KMS key or one of your own.
- **One IAM role per stack** — a single role is shared by every parameter and granted over the whole prefix. A grant per parameter races IAM propagation; this one does not.
- **Safe deletes** — removing the stack removes the parameter, and a parameter already deleted by hand does not wedge the delete.
- **Throttle-aware** — `SecureParameter.chain()` serialises a group of parameters, because Parameter Store throttles a burst of concurrent writes.
- **Reads its own value back** — `as_string_parameter()` and `as_ecs_secret()` hand the deployed parameter to whatever consumes it, resolved at runtime rather than at synthesis.
- **No Lambda, no Docker, no bundling** — built on the CDK's own `AwsCustomResource` singleton.
- **Typed** — ships a `py.typed` marker, so mypy and your IDE see the full signature.

## Installation

```bash
pip install callsy-cdk-secure-parameter
```

**Requirements:** Python >= 3.10, `aws-cdk-lib` >= 2.180.0.

## Quick start

```python
from aws_cdk import Stack
from callsy_cdk.secure_parameter import SecureParameter

class SecretsStack(Stack):
    def __init__(self, scope):
        super().__init__(scope, "SecretsStack")

        SecureParameter(
            scope=self,
            name="STRIPE_SECRET_KEY",
            description="Stripe secret key used by the billing service.",
            prefix="MyProject"
        )
```

Deploy, and you have `/MyProject/STRIPE_SECRET_KEY` in Parameter Store, encrypted, holding the placeholder `-`. Open the console (or run `aws ssm put-parameter --overwrite`) and set the real value once. Every deploy after that leaves it alone.

## How the value is managed

This is the whole point of the construct, so it is worth being explicit about what happens on each CloudFormation event.

| Event | What the construct does |
|---|---|
| **Create** | `ssm:PutParameter` with `Overwrite: false`, `Type: SecureString`, and the placeholder as the value. |
| **Update** | **Nothing.** No update call is registered, so a deploy can never overwrite the value you set by hand. |
| **Delete** | `ssm:DeleteParameter`. A `ParameterNotFound` error is tolerated, so a parameter you already removed does not block the delete. |

Two consequences worth knowing:

- **Changing `description` in code does nothing.** Because there is no update call, the description in Parameter Store keeps whatever it was given at create time. This is the deliberate cost of never rewriting the value.
- **A parameter that already exists fails the create.** `Overwrite: false` means `PutParameter` raises `ParameterAlreadyExists`, which is usually what you want — it stops a deploy from silently adopting a parameter it does not own. If a rolled-back stack has left one behind, pass `ignore_existing=True` to adopt it instead.

## Naming and the prefix

Every parameter is named `/<prefix>/<name>`:

```python
SecureParameter(scope=stack, name="STRIPE_SECRET_KEY", description="...", prefix="MyProject")
# -> /MyProject/STRIPE_SECRET_KEY
```

The prefix is what the shared IAM role is granted over (`arn:aws:ssm:<region>:<account>:parameter/MyProject/*`), and it is the default value of the `Project` tag. Use one prefix per project and environment, e.g. `MyProjectProd` and `MyProjectDev`.

If you already carry a project prefix in your own config, a thin wrapper keeps every call site short:

```python
def project_parameter(scope: Stack, name: str, description: str) -> SecureParameter:
    """
    Returns one secure parameter under this project's prefix.
    """
    return SecureParameter(scope=scope, name=name, description=description, prefix=config.prefix)
```

## Grouping parameters

Parameter Store throttles a burst of concurrent writes, and a stack with dozens of parameters will hit it. `chain()` makes each parameter depend on the one before it, so CloudFormation creates them one at a time.

```python
from callsy_cdk.secure_parameter import SecureParameter

parameters = [
    SecureParameter(scope=self, name="STRIPE_SECRET_KEY", description="...", prefix=prefix),
    SecureParameter(scope=self, name="STRIPE_WEBHOOK_SECRET", description="...", prefix=prefix),
    SecureParameter(scope=self, name="TWILIO_AUTH_TOKEN", description="...", prefix=prefix)
]

SecureParameter.chain(parameters)
```

## Reading the value back

The deployed value is never resolved at synthesis. These helpers hand the parameter to a consumer that reads it at runtime.

```python
# As a CDK parameter, for anything that takes an IStringParameter.
parameter = secure_parameter.as_string_parameter(scope=self)

# As a container secret, injected as an environment variable when the task starts.
container.add_container(
    "App",
    secrets={"STRIPE_SECRET_KEY": secure_parameter.as_ecs_secret(scope=self)}
)
```

Both helpers set `simple_name=False`, because the full name holds a slash and is therefore a path. Left undetected, the rendered ARN carries a doubled slash and matches nothing.

## API

### `SecureParameter(scope, name, description, *, prefix, ...)`

| Argument | Type | Default | Description |
|---|---|---|---|
| `scope` | `Stack` | — | The stack the parameter belongs to. The shared IAM role is built here. |
| `name` | `str` | — | The parameter name, appended to the prefix. A slash is allowed and is stripped from the construct id. |
| `description` | `str` | — | What the parameter holds. Set at create and never updated. |
| `prefix` | `str` | — | The project prefix. Keyword-only. |
| `tags` | `Mapping[str, str] \| None` | `{"Project": prefix}` | Tags applied to the parameter. |
| `placeholder` | `str` | `"-"` | The value written at create. |
| `key_id` | `str \| None` | `None` | KMS key id or alias. The account default key is used when omitted. |
| `tier` | `str \| None` | `None` | One of `Standard`, `Advanced` or `Intelligent-Tiering`. |
| `ignore_existing` | `bool` | `False` | Tolerate `ParameterAlreadyExists` on create, adopting a parameter left behind by a rolled-back stack. |

**Attributes**

| Attribute | Type | Description |
|---|---|---|
| `parameter_name` | `str` | The full name, `/<prefix>/<name>`. |
| `prefix` | `str` | The prefix this parameter was built with. |

**Methods**

| Method | Signature | Description |
|---|---|---|
| `build_name` | `build_name(prefix: str, name: str) -> str` | Static. The full name a parameter carries under a prefix, without building anything. |
| `chain` | `chain(parameters: Sequence[SecureParameter]) -> None` | Static. Makes each parameter wait for the one before it. |
| `as_string_parameter` | `as_string_parameter(scope, id=None) -> IStringParameter` | The deployed parameter, for anything taking an `IStringParameter`. |
| `as_ecs_secret` | `as_ecs_secret(scope, id=None) -> EcsSecret` | The deployed parameter, as a container secret. |

`SecureParameter` extends `AwsCustomResource`, so the whole construct API (`node`, `add_dependency`, and the rest) is available as usual.

### `get_role(scope, prefix) -> Role`

The IAM role every parameter of a stack shares, built on first use under the construct id `SecureParameterRole` and reused after that. Each new prefix widens its policy exactly once. Call it directly only if you need to grant the role something extra.

## IAM

The shared role is a Lambda execution role with `AWSLambdaBasicExecutionRole` and one statement per prefix:

```
ssm:PutParameter
ssm:AddTagsToResource
ssm:DeleteParameter
    on arn:aws:ssm:<region>:<account>:parameter/<prefix>/*
```

It holds no `ssm:GetParameter`, so the custom resource can create and delete a parameter but can never read one back.

## License

ISC
