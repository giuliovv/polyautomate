"""CDK Stack for Bot Platform infrastructure."""

from aws_cdk import (
    Stack,
    CfnOutput,
    RemovalPolicy,
    Duration,
    aws_cognito as cognito,
    aws_secretsmanager as secretsmanager,
    aws_kms as kms,
)
from constructs import Construct


class BotplatformStack(Stack):
    """Bot Platform infrastructure stack.

    This stack creates:
    - Cognito User Pool for authentication
    - KMS key for wallet encryption
    - Secrets Manager for sensitive config
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ===================
        # Cognito User Pool
        # ===================
        self.user_pool = cognito.UserPool(
            self,
            "BotplatformUserPool",
            user_pool_name="botplatform-users",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,  # Don't delete users on stack delete
        )

        # App client for frontend
        self.user_pool_client = self.user_pool.add_client(
            "BotplatformWebClient",
            user_pool_client_name="botplatform-web",
            generate_secret=False,  # Public client for browser
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                    implicit_code_grant=True,
                ),
                scopes=[
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[
                    "http://localhost:3000/",  # Local dev
                    "https://botplatform.example.com/",  # Production (update this)
                ],
                logout_urls=[
                    "http://localhost:3000/",
                    "https://botplatform.example.com/",
                ],
            ),
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
        )

        # ===================
        # KMS Key for Wallet Encryption
        # ===================
        self.wallet_encryption_key = kms.Key(
            self,
            "WalletEncryptionKey",
            alias="botplatform/wallet-encryption",
            description="Encrypts wallet private keys in Bot Platform",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ===================
        # Secrets Manager
        # ===================
        self.app_secrets = secretsmanager.Secret(
            self,
            "BotplatformSecrets",
            secret_name="botplatform/app-secrets",
            description="Application secrets for Bot Platform",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"SIGNER_SHARED_SECRET":""}',
                generate_string_key="SIGNER_SHARED_SECRET",
                exclude_punctuation=True,
                password_length=32,
            ),
        )

        # ===================
        # Outputs
        # ===================
        CfnOutput(
            self,
            "CognitoUserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
            export_name="BotplatformUserPoolId",
        )

        CfnOutput(
            self,
            "CognitoClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito App Client ID",
            export_name="BotplatformClientId",
        )

        CfnOutput(
            self,
            "KmsKeyArn",
            value=self.wallet_encryption_key.key_arn,
            description="KMS Key ARN for wallet encryption",
            export_name="BotplatformKmsKeyArn",
        )

        CfnOutput(
            self,
            "SecretsArn",
            value=self.app_secrets.secret_arn,
            description="Secrets Manager ARN",
            export_name="BotplatformSecretsArn",
        )
