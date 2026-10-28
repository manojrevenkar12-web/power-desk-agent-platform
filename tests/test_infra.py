"""CDK synth of the AWS stack, with cdk-nag (AWS Solutions) as a validation plugin. Slow-ish: jsii."""

import json
import sys

import pytest

from powerdesk.settings import ROOT

sys.path.insert(0, str(ROOT / "infra"))
pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    from app import build

    out = tmp_path_factory.mktemp("cdk")
    app, stack = build(outdir=str(out))
    app.synth()  # raises if cdk-nag reports an unacknowledged finding
    tpl = json.loads((out / f"{stack.stack_name}.template.json").read_text())
    report = json.loads((out / "validation-report.json").read_text())
    return tpl, report


def of(tpl, kind):
    return {k: r for k, r in tpl["Resources"].items() if r["Type"] == kind}


def test_cdk_nag_passes(synth):
    _, report = synth
    assert all(p["conclusion"] == "success" for p in report["pluginReports"])


def test_no_route_to_the_internet(synth):
    tpl, _ = synth
    assert not of(tpl, "AWS::EC2::NatGateway") and not of(tpl, "AWS::EC2::InternetGateway")
    assert len(of(tpl, "AWS::EC2::VPCEndpoint")) == 13


def test_two_gateways_with_jwt_and_interceptors(synth):
    tpl, _ = synth
    gws = of(tpl, "AWS::BedrockAgentCore::Gateway")
    assert len(gws) == 2
    for g in gws.values():
        p = g["Properties"]
        assert p["AuthorizerType"] == "CUSTOM_JWT" and p["ProtocolType"] == "MCP"
        points = sorted(i["InterceptionPoints"][0] for i in p["InterceptorConfigurations"])
        assert points == ["REQUEST", "RESPONSE"]
        assert all(i["InputConfiguration"]["PassRequestHeaders"] for i in p["InterceptorConfigurations"])


def test_developer_gateway_target_lists_no_book_tools(synth):
    tpl, _ = synth
    targets = of(tpl, "AWS::BedrockAgentCore::GatewayTarget")
    tool_sets = sorted(len(t["Properties"]["TargetConfiguration"]["Mcp"]["Lambda"]["ToolSchema"]["InlinePayload"]) for t in targets.values())
    assert tool_sets == [6, 12]


def test_runtime_in_the_vpc_with_jwt(synth):
    tpl, _ = synth
    (rt,) = of(tpl, "AWS::BedrockAgentCore::Runtime").values()
    p = rt["Properties"]
    assert p["NetworkConfiguration"]["NetworkMode"] == "VPC"
    assert "CustomJWTAuthorizer" in p["AuthorizerConfiguration"]
    assert p["RequestHeaderConfiguration"]["RequestHeaderAllowlist"] == ["Authorization"]


def test_data_is_encrypted_and_private(synth):
    tpl, _ = synth
    (db,) = of(tpl, "AWS::RDS::DBCluster").values()
    assert db["Properties"]["StorageEncrypted"] and db["Properties"]["EnableHttpEndpoint"]
    for b in of(tpl, "AWS::S3::Bucket").values():
        pab = b["Properties"]["PublicAccessBlockConfiguration"]
        assert all(pab[k] for k in ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"))
    (kb,) = of(tpl, "AWS::Bedrock::KnowledgeBase").values()
    assert kb["Properties"]["StorageConfiguration"]["Type"] == "RDS"
