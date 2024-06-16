#!/usr/bin/env python

# make sure environment variables are loaded before boto3 is imported
from dotenv import load_dotenv

load_dotenv()

import boto3
import json
from botocore.exceptions import ClientError
from rich import print

# Initialize clients
cognito_client = boto3.client("cognito-idp")
apigw_client = boto3.client("apigatewayv2")
lambda_client = boto3.client("lambda")
iam_client = boto3.client("iam")
logs_client = boto3.client("logs")


# Load state from JSON file
def load_state_from_file():
    with open("state.json", "r") as f:
        return json.load(f)


state = load_state_from_file()


# Decorator function to handle ResourceNotFoundException
def handle_resource_not_found(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"Resource not found: {e}")
            elif e.response["Error"]["Code"] == "ResourceNotFound":
                print(f"Resource not found: {e}")
            else:
                print(e)
        except Exception as e:
            print("Unknown Exception:", e)

    return wrapper


# Apply decorator to deletion functions
@handle_resource_not_found
def delete_lambda_function():
    lambda_client.delete_function(FunctionName=state["lambda_function_name"])
    print(f"Lambda function '{state['lambda_function_name']}' deleted")


@handle_resource_not_found
def delete_integration():
    apigw_client.delete_integration(
        ApiId=state["api_id"], IntegrationId=state["api_integration_id"]
    )
    print(f"Integration '{state['api_integration_id']}' deleted")


@handle_resource_not_found
def delete_integration_response():
    apigw_client.delete_integration_response(
        ApiId=state["api_id"],
        IntegrationId=state["api_integration_id"],
        IntegrationResponseId="default",
    )
    print("Integration response deleted")


@handle_resource_not_found
def delete_stage():
    apigw_client.delete_stage(ApiId=state["api_id"], StageName=state["api_stage_name"])
    print(f"Stage '{state['api_stage_name']}' deleted")


@handle_resource_not_found
def delete_user():
    response = cognito_client.admin_delete_user(
        UserPoolId=state["user_pool_id"], Username=state["user_pool_username"]
    )
    print(f"User '{state['user_pool_username']}' deleted")


@handle_resource_not_found
def delete_resource_server():
    response = cognito_client.delete_resource_server(
        UserPoolId=state["user_pool_id"],
        Identifier=state["user_pool_resource_server_id"],
    )
    print(f"Resource Server '{state['user_pool_resource_server_id']}' deleted")


@handle_resource_not_found
def delete_cognito_auth_domain():
    response = cognito_client.delete_user_pool_domain(
        Domain=state["user_pool_auth_domain_prefix"],
        UserPoolId=state["user_pool_id"],
    )
    print(f"Signup/signin domain '{state['user_pool_auth_domain']}' deleted")


@handle_resource_not_found
def delete_terminal_application():
    response = cognito_client.delete_user_pool_client(
        UserPoolId=state["user_pool_id"],
        ClientId=state["terminal_app_client_id"],
    )
    print("Terminal application deleted from user pool.")


@handle_resource_not_found
def delete_authorizer():
    apigw_client.delete_authorizer(
        ApiId=state["api_id"], AuthorizerId=state["api_authorizer_id"]
    )
    print(f"Authorizer '{state['api_authorizer_id']}' deleted")


@handle_resource_not_found
def delete_api():
    apigw_client.delete_api(ApiId=state["api_id"])
    print(f"API Gateway HTTP API '{state['api_id']}' deleted")


@handle_resource_not_found
def delete_lambda_role():
    try:
        iam_client.detach_role_policy(
            RoleName=state["lambda_role_name"],
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )
    except Exception as e:
        print(e)
    iam_client.delete_role(RoleName=state["lambda_role_name"])
    print("Lambda execution role deleted")


def delete_cloudwatch_logs():
    log_group_name = f"/aws/lambda/{state['lambda_function_name']}"
    paginator = logs_client.get_paginator("describe_log_streams")
    page_iterator = paginator.paginate(logGroupName=log_group_name)

    log_stream_names = []
    for page in page_iterator:
        log_streams = page["logStreams"]
        for log_stream in log_streams:
            log_stream_names.append(log_stream["logStreamName"])

    # Delete all log streams
    for log_stream_name in log_stream_names:
        logs_client.delete_log_stream(
            logGroupName=log_group_name, logStreamName=log_stream_name
        )

    # Finally, delete the log group
    logs_client.delete_log_group(logGroupName=log_group_name)
    print(f"Deleted log group: '{log_group_name}'")


@handle_resource_not_found
def delete_userpool():
    cognito_client.delete_user_pool(UserPoolId=state["user_pool_id"])
    print(f"Cognito User Pool '{state['user_pool_id']}' deleted")


@handle_resource_not_found
def delete_route():
    response = apigw_client.delete_route(
        ApiId=state["api_id"], RouteId=state["api_route_id"]
    )
    print(f"Route with ID '{state['api_route_id']}' deleted.")


# Execution of deletion functions
if __name__ == "__main__":
    delete_stage()
    delete_route()
    delete_integration()
    delete_lambda_function()
    delete_authorizer()
    delete_api()
    delete_lambda_role()
    delete_terminal_application()
    delete_resource_server()
    delete_user()
    delete_cognito_auth_domain()
    delete_userpool()
    print("All resources deleted successfully")
