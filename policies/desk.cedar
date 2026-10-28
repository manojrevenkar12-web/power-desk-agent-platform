// Who may do what on the desk agent platform. Evaluated at the tool gateway before any tool runs
// and on every knowledge-base hit before it reaches a model. Deny by default: anything not
// permitted here is refused. A forbid always wins over a permit.
// The same rules load into Amazon Bedrock AgentCore Policy, which also evaluates Cedar.

@id("market-and-knowledge-tools")
permit (principal, action == Action::"invoke_tool", resource)
when { resource.data_class == "market" || resource.data_class == "knowledge" };

@id("book-tools-for-front-office-and-risk")
permit (principal, action == Action::"invoke_tool", resource)
when { resource.data_class == "book" && ["trader", "originator", "risk"].contains(principal.role) };

@id("no-book-data-in-developer-tools")
forbid (principal, action == Action::"invoke_tool", resource)
when { resource.data_class == "book" && context.surface == "developer_tools" };

@id("own-desk-books")
permit (principal, action == Action::"read_book", resource)
when { resource.desk == principal.desk && ["trader", "originator"].contains(principal.role) };

@id("risk-reads-every-book")
permit (principal, action == Action::"read_book", resource)
when { principal.role == "risk" };

@id("originators-only-origination-books")
forbid (principal, action == Action::"read_book", resource)
when { principal.role == "originator" && resource.kind != "ppa" };

@id("open-documents")
permit (principal, action == Action::"read_document", resource)
when { resource.classification == "internal" };

@id("confidential-documents-own-desk")
permit (principal, action == Action::"read_document", resource)
when { resource.classification == "confidential" && (resource.desk == principal.desk || principal.role == "risk") };

@id("inside-information-insiders-only")
permit (principal, action == Action::"read_document", resource)
when { resource.classification == "inside_information" && principal.insider_lists.contains(resource.insider_list) };

@id("inside-information-never-outside-the-list")
forbid (principal, action == Action::"read_document", resource)
when { resource.classification == "inside_information" && !principal.insider_lists.contains(resource.insider_list) };

@id("user-scope-owner-only")
forbid (principal, action == Action::"read_document", resource)
when { resource.scope == "user" && resource.owner != principal.id };

@id("chat-scope-this-chat-only")
forbid (principal, action == Action::"read_document", resource)
when { resource.scope == "chat" && resource.chat != context.chat };

@id("agent-scope-this-agent-only")
forbid (principal, action == Action::"read_document", resource)
when { resource.scope == "agent" && resource.agent != context.agent };
