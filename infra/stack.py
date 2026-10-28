"""The desk platform in one AWS account and region (CDK, Python).

- A VPC with isolated subnets only: no NAT, no internet gateway. AWS services are reached through
  VPC endpoints (Bedrock, Bedrock Agent Runtime, AgentCore, ECR, logs, Secrets Manager, KMS, STS,
  RDS Data, S3 gateway).
- Aurora PostgreSQL Serverless v2 with pgvector and the Data API, encrypted with a customer key:
  the Bedrock knowledge base's vector store.
- A Bedrock knowledge base over Aurora (Titan Text Embeddings v2) with an S3 data source; each
  document carries metadata (classification, scope, desk, owner, insider list) that the
  entitlement filter uses at retrieval time.
- One build, two arm64 images in ECR (see Dockerfile): `<version>-lambda` for the tool Lambda and
  the gateway interceptors, `<version>-runtime` for the agent on AgentCore Runtime.
- Two AgentCore Gateways, one per surface (desk agents; developer tools), each with JWT inbound
  auth from the firm's identity provider, a REQUEST and a RESPONSE interceptor, and a Lambda
  target whose tool schemas come from `powerdesk export-schemas`. The developer-tools gateway's
  target lists no book tools at all.
- An S3 bucket for agent skills (SKILL.md), read by the AgentCore harness through the S3 endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import (
    aws_bedrock as bedrock,
)
from aws_cdk import (
    aws_bedrockagentcore as agentcore,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_ecr as ecr,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_kms as kms,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_rds as rds,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_secretsmanager as sm,
)
from constructs import Construct

ROOT = Path(__file__).resolve().parents[1]
SURFACES = {"desk": "desk_agent", "dev": "developer_tools"}


def schema_property(s: dict[str, Any]) -> agentcore.CfnGatewayTarget.SchemaDefinitionProperty:
    return agentcore.CfnGatewayTarget.SchemaDefinitionProperty(
        type=s["type"],
        description=s.get("description"),
        properties={k: schema_property(v) for k, v in s.get("properties", {}).items()} or None,
        required=s.get("required") or None,
        items=schema_property(s["items"]) if "items" in s else None,
    )


def tool_definitions(surface: str) -> list[agentcore.CfnGatewayTarget.ToolDefinitionProperty]:
    tools = json.loads((ROOT / "infra" / "schemas" / f"{surface}.json").read_text())
    return [agentcore.CfnGatewayTarget.ToolDefinitionProperty(name=t["name"], description=t["description"], input_schema=schema_property(t["inputSchema"])) for t in tools]


class DeskPlatformStack(cdk.Stack):
    def __init__(self, scope: Construct, cid: str, cfg: dict[str, Any], **kw: Any) -> None:
        super().__init__(scope, cid, **kw)
        name = f"powerdesk-{cfg['env_name']}"
        key = kms.Key(self, "Key", enable_key_rotation=True, alias=f"alias/{name}", removal_policy=cdk.RemovalPolicy.RETAIN)

        # --- network: isolated subnets, endpoints only -------------------------------------------
        flow_logs = logs.LogGroup(self, "FlowLogs", retention=logs.RetentionDays.ONE_YEAR, encryption_key=key)
        vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr(cfg["vpc"]["cidr"]),
            max_azs=cfg["vpc"]["max_azs"],
            nat_gateways=0,
            subnet_configuration=[ec2.SubnetConfiguration(name="isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24)],
            flow_logs={"all": ec2.FlowLogOptions(destination=ec2.FlowLogDestination.to_cloud_watch_logs(flow_logs))},
        )
        endpoint_sg = ec2.SecurityGroup(self, "EndpointSg", vpc=vpc, description="VPC interface endpoints", allow_all_outbound=False)
        endpoint_sg.add_ingress_rule(ec2.Peer.ipv4(cfg["vpc"]["cidr"]), ec2.Port.tcp(443), "HTTPS from the VPC")
        for eid, svc in {
            "Bedrock": ec2.InterfaceVpcEndpointAwsService.BEDROCK,
            "BedrockRuntime": ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
            "BedrockAgentRuntime": ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENT_RUNTIME,
            "AgentCore": ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENTCORE,
            "AgentCoreGateway": ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENTCORE_GATEWAY,
            "Ecr": ec2.InterfaceVpcEndpointAwsService.ECR,
            "EcrDocker": ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
            "Logs": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            "Secrets": ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            "Kms": ec2.InterfaceVpcEndpointAwsService.KMS,
            "Sts": ec2.InterfaceVpcEndpointAwsService.STS,
            "RdsData": ec2.InterfaceVpcEndpointAwsService.RDS_DATA,
        }.items():
            vpc.add_interface_endpoint(eid, service=svc, security_groups=[endpoint_sg], private_dns_enabled=True, open=False)
        vpc.add_gateway_endpoint("S3", service=ec2.GatewayVpcEndpointAwsService.S3)

        # --- Aurora PostgreSQL with pgvector, the knowledge base store ----------------------------
        db_sg = ec2.SecurityGroup(self, "DbSg", vpc=vpc, description="Aurora", allow_all_outbound=False)
        app_sg = ec2.SecurityGroup(self, "AppSg", vpc=vpc, description="Lambdas and agent runtime", allow_all_outbound=False)
        # HTTPS to anywhere is safe here: the subnets have no route out, only the VPC endpoints and
        # the S3 gateway endpoint (whose prefix list is not inside the VPC CIDR) are reachable.
        app_sg.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "VPC endpoints and the S3 gateway endpoint")
        app_sg.add_egress_rule(db_sg, ec2.Port.tcp(5432), "Aurora")
        db_sg.add_ingress_rule(app_sg, ec2.Port.tcp(5432), "from the app")
        cluster = rds.DatabaseCluster(
            self,
            "Db",
            engine=rds.DatabaseClusterEngine.aurora_postgres(version=rds.AuroraPostgresEngineVersion.of(cfg["aurora"]["engine"], cfg["aurora"]["engine"].split(".")[0])),
            writer=rds.ClusterInstance.serverless_v2("writer"),
            readers=[rds.ClusterInstance.serverless_v2("reader", scale_with_writer=True)],
            serverless_v2_min_capacity=cfg["aurora"]["min_acu"],
            serverless_v2_max_capacity=cfg["aurora"]["max_acu"],
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[db_sg],
            default_database_name=cfg["knowledge_base"]["database"],
            storage_encrypted=True,
            storage_encryption_key=key,
            credentials=rds.Credentials.from_generated_secret("powerdesk_admin", encryption_key=key),
            enable_data_api=True,
            iam_authentication=True,
            deletion_protection=True,
            backup=rds.BackupProps(retention=cdk.Duration.days(14)),
            cloudwatch_logs_exports=["postgresql"],
            removal_policy=cdk.RemovalPolicy.SNAPSHOT,
        )
        assert cluster.secret is not None
        cluster.add_rotation_single_user(automatically_after=cdk.Duration.days(30), vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED))

        # --- documents and skills ---------------------------------------------------------------
        access_logs = s3.Bucket(
            self, "AccessLogs", encryption=s3.BucketEncryption.S3_MANAGED, block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True, removal_policy=cdk.RemovalPolicy.RETAIN
        )

        def bucket(bid: str) -> s3.Bucket:
            return s3.Bucket(
                self,
                bid,
                encryption=s3.BucketEncryption.KMS,
                encryption_key=key,
                bucket_key_enabled=True,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                enforce_ssl=True,
                versioned=True,
                server_access_logs_bucket=access_logs,
                server_access_logs_prefix=f"{bid.lower()}/",
                removal_policy=cdk.RemovalPolicy.RETAIN,
            )

        docs = bucket("Documents")
        skills = bucket("Skills")

        # --- Bedrock knowledge base over Aurora -------------------------------------------------
        kb_role = iam.Role(self, "KbRole", assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
        docs.grant_read(kb_role)
        cluster.secret.grant_read(kb_role)
        embed_arn = f"arn:{self.partition}:bedrock:{self.region}::foundation-model/{cfg['knowledge_base']['embedding_model']}"
        kb_role.add_to_policy(iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=[embed_arn]))
        kb_role.add_to_policy(iam.PolicyStatement(actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement", "rds:DescribeDBClusters"], resources=[cluster.cluster_arn]))
        kb = bedrock.CfnKnowledgeBase(
            self,
            "KnowledgeBase",
            name=f"{name}-kb",
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR", vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(embedding_model_arn=embed_arn)
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="RDS",
                rds_configuration=bedrock.CfnKnowledgeBase.RdsConfigurationProperty(
                    resource_arn=cluster.cluster_arn,
                    credentials_secret_arn=cluster.secret.secret_arn,
                    database_name=cfg["knowledge_base"]["database"],
                    table_name=cfg["knowledge_base"]["table"],
                    field_mapping=bedrock.CfnKnowledgeBase.RdsFieldMappingProperty(
                        primary_key_field="id", vector_field="embedding", text_field="chunks", metadata_field="metadata", custom_metadata_field="custom_metadata"
                    ),
                ),
            ),
        )
        bedrock.CfnDataSource(
            self,
            "KbDocuments",
            knowledge_base_id=kb.attr_knowledge_base_id,
            name="desk-documents",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3", s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(bucket_arn=docs.bucket_arn, inclusion_prefixes=["kb/"])
            ),
            server_side_encryption_configuration=bedrock.CfnDataSource.ServerSideEncryptionConfigurationProperty(kms_key_arn=key.key_arn),
        )

        # --- one image, three entry points -----------------------------------------------------
        repo = ecr.Repository.from_repository_name(self, "Repo", cfg["image"]["repository"])
        identity_key = sm.Secret(
            self,
            "IdentityKey",
            description="Signs the caller identity between interceptor and tool Lambda",
            encryption_key=key,
            generate_secret_string=sm.SecretStringGenerator(password_length=48, exclude_punctuation=True),
        )
        cdk.Validations.of(identity_key).acknowledge(
            cdk.Acknowledgment(
                id="AwsSolutions::AwsSolutions-SMG4",
                reason="Rotated by the release runbook together with both Lambdas that hold it (envelopes live 120 s); a rotation Lambda cannot restart them atomically.",
            )
        )
        oidc = cfg["oidc"]
        issuer = oidc["discovery_url"].removesuffix("/.well-known/openid-configuration")
        common_env = {
            "POWERDESK_ENV": "prod",
            "POWERDESK_OIDC_ISSUER": issuer,
            "POWERDESK_OIDC_JWKS_URL": issuer.removesuffix("/v2.0") + "/discovery/v2.0/keys",
            "POWERDESK_OIDC_AUDIENCE": oidc["audience"],
            "POWERDESK_USER_CLAIM": oidc["user_claim"],
            "POWERDESK_IDENTITY_KEY_SECRET_ARN": identity_key.secret_arn,
            "POWERDESK_KB_ID": kb.attr_knowledge_base_id,
        }

        def fn(fid: str, cmd: str, extra: dict[str, str] | None = None) -> lambda_.DockerImageFunction:
            f = lambda_.DockerImageFunction(
                self,
                fid,
                code=lambda_.DockerImageCode.from_ecr(repo, tag_or_digest=f"{cfg['image']['tag']}-lambda", cmd=[cmd]),
                architecture=lambda_.Architecture.ARM_64,
                memory_size=1024,
                timeout=cdk.Duration.seconds(30),
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
                security_groups=[app_sg],
                environment={**common_env, **(extra or {})},
                environment_encryption=key,
                tracing=lambda_.Tracing.ACTIVE,
                reserved_concurrent_executions=50,
                log_group=logs.LogGroup(self, f"{fid}Logs", retention=logs.RetentionDays.ONE_YEAR, encryption_key=key),
            )
            identity_key.grant_read(f)
            return f

        tools_fn = fn("ToolFn", "powerdesk.aws.tool_lambda.handler")
        tools_fn.add_to_role_policy(iam.PolicyStatement(actions=["bedrock:Retrieve"], resources=[kb.attr_knowledge_base_arn]))

        # --- one AgentCore Gateway per surface ---------------------------------------------------
        authorizer = agentcore.CfnGateway.AuthorizerConfigurationProperty(
            custom_jwt_authorizer=agentcore.CfnGateway.CustomJWTAuthorizerConfigurationProperty(discovery_url=oidc["discovery_url"], allowed_audience=[oidc["audience"]])
        )
        self.gateways: dict[str, agentcore.CfnGateway] = {}
        for short, surface in SURFACES.items():
            role = iam.Role(self, f"{short.title()}GatewayRole", assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
            req = fn(f"{short.title()}RequestInterceptor", "powerdesk.aws.interceptors.request_handler", {"POWERDESK_SURFACE": surface})
            resp = fn(f"{short.title()}ResponseInterceptor", "powerdesk.aws.interceptors.response_handler", {"POWERDESK_SURFACE": surface})
            for f in (tools_fn, req, resp):
                f.grant_invoke(role)
            gw = agentcore.CfnGateway(
                self,
                f"{short.title()}Gateway",
                name=f"{name}-{short}",
                description=f"Desk tools for the {surface} surface",
                protocol_type="MCP",
                protocol_configuration=agentcore.CfnGateway.GatewayProtocolConfigurationProperty(
                    mcp=agentcore.CfnGateway.MCPGatewayConfigurationProperty(supported_versions=cfg["mcp"]["supported_versions"], instructions="European power desk tools. State numbers as returned.")
                ),
                authorizer_type="CUSTOM_JWT",
                authorizer_configuration=authorizer,
                role_arn=role.role_arn,
                kms_key_arn=key.key_arn,
                exception_level="DEBUG" if cfg["env_name"] == "dev" else None,
                interceptor_configurations=[
                    agentcore.CfnGateway.GatewayInterceptorConfigurationProperty(
                        interception_points=["REQUEST"],
                        interceptor=agentcore.CfnGateway.InterceptorConfigurationProperty(lambda_=agentcore.CfnGateway.LambdaInterceptorConfigurationProperty(arn=req.function_arn)),
                        input_configuration=agentcore.CfnGateway.InterceptorInputConfigurationProperty(pass_request_headers=True),
                    ),
                    agentcore.CfnGateway.GatewayInterceptorConfigurationProperty(
                        interception_points=["RESPONSE"],
                        interceptor=agentcore.CfnGateway.InterceptorConfigurationProperty(lambda_=agentcore.CfnGateway.LambdaInterceptorConfigurationProperty(arn=resp.function_arn)),
                        input_configuration=agentcore.CfnGateway.InterceptorInputConfigurationProperty(pass_request_headers=True),
                    ),
                ],
            )
            key.grant_encrypt_decrypt(role)
            agentcore.CfnGatewayTarget(
                self,
                f"{short.title()}Tools",
                gateway_identifier=gw.attr_gateway_identifier,
                name="desk",
                description="Market, book and knowledge tools, Cedar-checked in the Lambda",
                target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                    mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                        lambda_=agentcore.CfnGatewayTarget.McpLambdaTargetConfigurationProperty(
                            lambda_arn=tools_fn.function_arn, tool_schema=agentcore.CfnGatewayTarget.ToolSchemaProperty(inline_payload=tool_definitions(surface))
                        )
                    )
                ),
                credential_provider_configurations=[agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(credential_provider_type="GATEWAY_IAM_ROLE")],
            )
            self.gateways[short] = gw
            cdk.CfnOutput(self, f"{short.title()}GatewayUrl", value=gw.attr_gateway_url)

        # --- the desk agent on AgentCore Runtime --------------------------------------------------
        runtime_role = iam.Role(self, "RuntimeRole", assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
        repo.grant_pull(runtime_role)
        identity_key.grant_read(runtime_role)
        key.grant_decrypt(runtime_role)
        skills.grant_read(runtime_role)
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"],
                resources=[f"arn:{self.partition}:bedrock:*::foundation-model/anthropic.*", f"arn:{self.partition}:bedrock:{self.region}:{self.account}:inference-profile/eu.anthropic.*"],
            )
        )
        runtime_role.add_to_policy(iam.PolicyStatement(actions=["bedrock:Retrieve"], resources=[kb.attr_knowledge_base_arn]))
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[f"arn:{self.partition}:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/runtimes/*"],
            )
        )
        runtime = agentcore.CfnRuntime(
            self,
            "AgentRuntime",
            agent_runtime_name=f"{name.replace('-', '_')}_agent",
            description="The desk research agent (Converse, grounded answers)",
            role_arn=runtime_role.role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(container_uri=f"{repo.repository_uri}:{cfg['image']['tag']}-runtime")
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="VPC",
                network_mode_config=agentcore.CfnRuntime.VpcConfigProperty(
                    security_groups=[app_sg.security_group_id], subnets=vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED).subnet_ids
                ),
            ),
            authorizer_configuration=agentcore.CfnRuntime.AuthorizerConfigurationProperty(
                custom_jwt_authorizer=agentcore.CfnRuntime.CustomJWTAuthorizerConfigurationProperty(discovery_url=oidc["discovery_url"], allowed_audience=[oidc["audience"]])
            ),
            request_header_configuration=agentcore.CfnRuntime.RequestHeaderConfigurationProperty(request_header_allowlist=["Authorization"]),
            protocol_configuration="HTTP",
            environment_variables={**common_env, "POWERDESK_MODEL": "bedrock", "POWERDESK_SKILLS_BUCKET": skills.bucket_name},
        )
        cdk.CfnOutput(self, "AgentRuntimeArn", value=runtime.attr_agent_runtime_arn)
        cdk.CfnOutput(self, "KnowledgeBaseId", value=kb.attr_knowledge_base_id)
        cdk.CfnOutput(self, "SkillsBucket", value=skills.bucket_name)
        cdk.CfnOutput(self, "DocumentsBucket", value=docs.bucket_name)
