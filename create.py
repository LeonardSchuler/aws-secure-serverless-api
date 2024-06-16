#!/usr/bin/env python

# make sure environment variables are loaded before boto3 is imported
from dotenv import load_dotenv

load_dotenv()

import os
import boto3
import json
import zipfile
import io
import time

from rich import print

# Initialize clients
cognito_client = boto3.client("cognito-idp")
apigw_client = boto3.client("apigatewayv2")
lambda_client = boto3.client("lambda")
iam_client = boto3.client("iam")

# State dictionary to store created resource IDs


def load_state_from_file():
    with open("state.json", "r") as f:
        return json.load(f)


def create_userpool():
    response = cognito_client.create_user_pool(
        PoolName=state["user_pool_name"],
        AutoVerifiedAttributes=["email"],
        Policies={
            "PasswordPolicy": {
                "MinimumLength": 8,
                "RequireUppercase": False,
                "RequireLowercase": False,
                "RequireNumbers": False,
                "RequireSymbols": False,
                "TemporaryPasswordValidityDays": 7,
            }
        },
        Schema=[{"Name": "email", "Required": True, "AttributeDataType": "String"}],
    )
    state["user_pool_id"] = response["UserPool"]["Id"]
    issuer_url = (
        f'https://cognito-idp.{state["region"]}.amazonaws.com/{state["user_pool_id"]}'
    )
    state["user_pool_jwt_issuer_url"] = issuer_url
    print(f"User Pool created with ID: '{state['user_pool_id']}'")


def create_user_pool_authentication_domain(domain_prefix):
    response = cognito_client.create_user_pool_domain(
        Domain=domain_prefix,
        UserPoolId=state["user_pool_id"],
    )
    state["user_pool_auth_domain_prefix"] = domain_prefix
    state["user_pool_auth_domain"] = (
        f"https://{domain_prefix}.auth.{state['region']}.amazoncognito.com"
    )
    print(
        f"User pool signup/signin page created at: '{state['user_pool_auth_domain']}'"
    )


def create_resource_server():
    response = cognito_client.create_resource_server(
        UserPoolId=state["user_pool_id"],
        Identifier=state["api_name"],
        Name=state["api_name"],
        Scopes=[
            {"ScopeName": name, "ScopeDescription": description}
            for (name, description) in state["api_scopes"]
        ],
    )
    state["user_pool_resource_server_id"] = response["ResourceServer"]["Identifier"]
    print(f"Resource Server created with ID: '{state['user_pool_resource_server_id']}'")


def create_terminal_app_client():
    response = cognito_client.create_user_pool_client(
        UserPoolId=state["user_pool_id"],
        ClientName="Terminal Application",
        GenerateSecret=False,
        AllowedOAuthFlows=["code"],
        AllowedOAuthScopes=state["terminal_app_scopes"],
        CallbackURLs=state["terminal_app_callback_urls"],
        AllowedOAuthFlowsUserPoolClient=True,
        SupportedIdentityProviders=["COGNITO"],
    )
    state["terminal_app_client_id"] = response["UserPoolClient"]["ClientId"]
    print(
        f"Terminal app Client created with client id: '{state['terminal_app_client_id']}'"
    )


def create_api():
    response = apigw_client.create_api(Name=state["api_name"], ProtocolType="HTTP")
    state["api_id"] = response["ApiId"]
    print(
        f"API Gateway '{state['api_name']}' HTTP API created with ID: '{state['api_id']}'"
    )


def create_authorizer():
    response = apigw_client.create_authorizer(
        ApiId=state["api_id"],
        Name="MyAuthorizer",
        AuthorizerType="JWT",
        IdentitySource=["$request.header.Authorization"],
        JwtConfiguration={
            "Issuer": state["user_pool_jwt_issuer_url"],
            "Audience": [state["terminal_app_client_id"]],
        },
    )
    state["api_authorizer_id"] = response["AuthorizerId"]
    print(f"Authorizer created with ID: '{state['api_authorizer_id']}'")


def create_lambda_role():
    assume_role_policy = """{
	"Version": "2012-10-17",
	"Statement": [
		{
			"Sid": "TrustedService",
			"Effect": "Allow",
			"Principal": {
				"Service": "lambda.amazonaws.com"
			},
			"Action": "sts:AssumeRole"
		}
	]
}"""

    response = iam_client.create_role(
        RoleName=state["lambda_role_name"],
        AssumeRolePolicyDocument=assume_role_policy,
    )
    role_arn = response["Role"]["Arn"]
    iam_client.attach_role_policy(
        RoleName=state["lambda_role_name"],
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )
    state["lambda_role_arn"] = role_arn
    print(f"Lambda execution role created with ARN: '{state['lambda_role_arn']}'")


def create_lambda_function(role_arn):
    lambda_code = """
def lambda_handler(event, context):
    print("------------------------")
    print(event)
    print(context)
    print("------------------------")
    return "hello world"
"""

    # Create a zip file containing the Lambda function code
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, mode="w") as zf:
        zf.writestr("lambda_function.py", lambda_code.encode("utf-8"))
    zip_io.seek(0)
    waiter = iam_client.get_waiter("role_exists")
    waiter.wait(RoleName=state["lambda_role_name"])

    print(f"Creating lambda with role '{role_arn}'")
    response = lambda_client.create_function(
        FunctionName=state["lambda_function_name"],
        Runtime="python3.11",
        Role=role_arn,
        Handler="lambda_function.lambda_handler",
        Code={"ZipFile": zip_io.read()},
        Architectures=["arm64"],
        Description="Lambda function for echoing hello world",
    )
    print(f"Lambda function created with name: '{state['lambda_function_name']}'")


def add_permission_for_apigw_to_invoke_lambda():
    lambda_client.add_permission(
        FunctionName=state["lambda_function_name"],
        StatementId=f"apigateway-{state['api_id']}",
        Action="lambda:InvokeFunction",
        Principal="apigateway.amazonaws.com",
        SourceArn=f"arn:aws:execute-api:{state['region']}:{boto3.client('sts').get_caller_identity()['Account']}:{state['api_id']}/*/*",
    )
    print("Permission added to Lambda function for API Gateway to invoke it.")


def create_integration():
    response = apigw_client.create_integration(
        ApiId=state["api_id"],
        IntegrationType="AWS_PROXY",
        IntegrationUri=f"arn:aws:lambda:{boto3.session.Session().region_name}:{boto3.client('sts').get_caller_identity()['Account']}:function:{state['lambda_function_name']}",
        IntegrationMethod="GET",
        PayloadFormatVersion="2.0",
    )
    state["api_integration_id"] = response["IntegrationId"]
    print(f"Integration created with ID: '{state['api_integration_id']}'")


def create_route():
    route_key = f"{state['api_route_method']} {state['api_route_path']}"
    # ! AutzorizationScopes are ORed not ANDed
    # i.e. any autzorization scope in the access token gives access
    response = apigw_client.create_route(
        ApiId=state["api_id"],
        RouteKey=route_key,
        AuthorizationType="JWT",
        AuthorizationScopes=[
            f"{state['api_name']}/{scope}" for scope, description in state["api_scopes"]
        ],
        AuthorizerId=state["api_authorizer_id"],
        Target=f'integrations/{state["api_integration_id"]}',
    )
    state["api_route_id"] = response["RouteId"]
    print(f"Route '{route_key}' created with ID: '{state['api_route_id']}'")


def create_stage():
    response = apigw_client.create_stage(
        ApiId=state["api_id"], StageName=state["api_stage_name"], AutoDeploy=True
    )
    print(f"(Auto deploy) stage created with name: '{state['api_stage_name']}'")


def create_user(username, email, password):
    if "user_pool_id" not in state:
        print("User Pool ID not found in state.")
        return

    response = cognito_client.admin_create_user(
        UserPoolId=state["user_pool_id"],
        Username=username,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ],
        MessageAction="SUPPRESS",
    )
    response = cognito_client.admin_set_user_password(
        UserPoolId=state["user_pool_id"],
        Username=username,
        Password=password,
        Permanent=True,
    )

    print(
        f"User '{username}' created with email '{email}' in User Pool '{state['user_pool_id']}'."
    )


def save_state_to_file():
    with open("state.json", "w") as f:
        json.dump(state, f, indent=4)
    print("State saved to state.json")


if __name__ == "__main__":
    state = {
        "region": boto3.session.Session().region_name,
        "user_pool_name": "HelloUserPool",
        "user_pool_jwt_issuer_url": "",
        "user_pool_username": "Testuser",
        "user_pool_email": "testuser@example.com",
        "api_name": "HelloAPI",
        "api_route_path": "/hello",
        "api_route_method": "GET",
        "lambda_function_name": "EchoFunction",
        "lambda_role_name": "APIGatewayLambdaRole",
        "api_stage_name": "dev",
        "api_scopes": [
            ("hello.read", "Allows read access to the hello API"),
            ("hello.write", "Allows writing"),
        ],
        "terminal_app_callback_urls": ["http://localhost:8083/callback"],
        # Following keys will be populated by script
        # "user_pool_id": "",
        # "api_id": "",
        # "api_route_id": "",
        # "api_authorizer_id": "",
        # "api_integration_id": "",
        # "lambda_role_arn": "",
        # "user_pool_resource_server_id": "",
        # "terminal_app_client_id": "",
        # "user_pool_auth_domain": ""
    }
    state["terminal_app_scopes"] = [
        "openid",
        "profile",
        "email",
        f"{state['api_name']}/hello.read",  # cognito prefixes custom scopes
    ]

    try:
        PASSWORD = os.environ["PASSWORD"]
        DOMAIN_PREFIX = os.environ["DOMAIN_PREFIX"]
    except KeyError:
        raise RuntimeError(
            "Provide 'PASSWORD' and 'DOMAIN_PREFIX' environment variables."
        )

    try:
        create_userpool()
        create_user_pool_authentication_domain(DOMAIN_PREFIX)
        create_resource_server()
        create_terminal_app_client()
        create_user(state["user_pool_username"], state["user_pool_email"], PASSWORD)

        create_api()
        create_authorizer()

        # IAM is not strongly consistent, role exists but trust policy may not
        # waiter on role creation does not work
        # small TODO: wait on availabiltiy of trust policy instead of sleep
        create_lambda_role()
        time.sleep(10)

        create_lambda_function(state["lambda_role_arn"])
        add_permission_for_apigw_to_invoke_lambda()
        create_integration()
        create_route()
        create_stage()
        api_url = f"https://{state['api_id']}.execute-api.{state['region']}.amazonaws.com/{state['api_stage_name']}{state['api_route_path']}"
        print(f"API available at: '{api_url}'")
        state["api_url"] = api_url
    except Exception as e:
        print(e)

    save_state_to_file()
