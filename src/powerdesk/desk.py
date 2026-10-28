"""Wiring: one authoriser, knowledge base, tool gateway and agent, with the model chosen by
environment. `POWERDESK_MODEL=bedrock` uses Amazon Bedrock (Converse) with the default AWS
credentials and region; anything else uses the simulated model from config/sim.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass

from powerdesk.agent.runtime import BedrockModel, DeskAgent, Model, load_agent_settings
from powerdesk.agent.sim import SimModel
from powerdesk.kb.search import KnowledgeBase
from powerdesk.policy import Authorizer
from powerdesk.settings import read_yaml
from powerdesk.tools.gateway import ToolGateway


@dataclass
class Desk:
    authz: Authorizer
    kb: KnowledgeBase
    gateway: ToolGateway
    agent: DeskAgent


def sim_model(obey_injected_instructions: bool | None = None, derived_number_rate: float | None = None) -> SimModel:
    cfg = read_yaml("config/sim.yaml")
    return SimModel(
        derived_number_rate=cfg["derived_number_rate"] if derived_number_rate is None else derived_number_rate,
        obey_injected_instructions=cfg["obey_injected_instructions"] if obey_injected_instructions is None else obey_injected_instructions,
    )


def default_model() -> Model:
    if os.environ.get("POWERDESK_MODEL") == "bedrock":
        import boto3

        return BedrockModel(boto3.client("bedrock-runtime"), load_agent_settings().model.bedrock_model_id)
    return sim_model()


def build_desk(model: Model | None = None, kb: KnowledgeBase | None = None, ground: bool = True) -> Desk:
    authz = Authorizer()
    kb = kb or KnowledgeBase(authorizer=authz)
    gateway = ToolGateway(authz, search=lambda ctx, q, scopes, k: kb.search(ctx, q, scopes, k))
    return Desk(authz, kb, gateway, DeskAgent(model or default_model(), gateway, ground=ground))
