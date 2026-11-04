import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  ApiError,
  api,
  getWorkspace,
  type Agent,
  type Inventory,
  type Service,
} from "../api";
import {
  ChoiceList,
  FormIntro,
  FormPage,
  FormRow,
  ReviewList,
  type Choice,
} from "../components/FormPage";
import { Shell } from "../components/Shell";
import { ErrorBox, Skeleton } from "../components/ui";
import { useAsync } from "../hooks";

const SERVICE_KINDS: Choice[] = [
  {
    value: "http",
    title: "HTTP API",
    description: "REST service discovered from an OpenAPI document.",
  },
  {
    value: "mcp_http",
    title: "MCP server",
    description: "Model Context Protocol over streamable HTTP.",
  },
  {
    value: "a2a",
    title: "Remote agent",
    description: "Another agent reachable over A2A.",
  },
];

const AGENT_KINDS: Choice[] = [
  {
    value: "interactive",
    title: "Interactive",
    description: "Acts on behalf of a person during a session.",
  },
  {
    value: "autonomous",
    title: "Autonomous",
    description: "Runs on its own schedule with a fixed ceiling.",
  },
  {
    value: "service",
    title: "Service",
    description: "Background worker that calls tools without a user.",
  },
];

export function ResourceForm() {
  const { type, id } = useParams();
  const [params] = useSearchParams();
  const kind = type ?? params.get("type") ?? "service";
  if (kind === "agent") return <AgentForm id={id} />;
  if (kind === "service") return <ServiceForm id={id} />;
  return (
    <Shell title="Unknown resource" crumbs={[{ label: "All resources", to: "/resources" }]}>
      <div className="callout callout--error">
        Unknown resource type “{kind}”. <Link to="/resources">Back to all resources</Link>.
      </div>
    </Shell>
  );
}

function useGroups() {
  const ws = getWorkspace();
  const inventory = useAsync(() => api<Inventory>(`/v1/workspaces/${ws}/inventory`), [ws]);
  return {
    groups: inventory.data?.groups ?? [],
    loading: inventory.loading,
    error: inventory.error,
    reload: inventory.reload,
  };
}

function ServiceForm({ id }: { id?: string }) {
  const editing = Boolean(id);
  const ws = getWorkspace();
  const navigate = useNavigate();
  const groups = useGroups();
  const service = useAsync<Service | null>(
    () =>
      id
        ? api<Service>(`/v1/workspaces/${ws}/services/${id}`)
        : Promise.resolve(null),
    [ws, id],
  );

  const [name, setName] = useState("");
  const [kind, setKind] = useState("http");
  const [endpoint, setEndpoint] = useState("");
  const [authType, setAuthType] = useState("none");
  const [credentialPolicy, setCredentialPolicy] = useState("per_agent");
  const [status, setStatus] = useState("active");
  const [groupId, setGroupId] = useState("");
  const [touched, setTouched] = useState({ name: false, endpoint: false });
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const current = service.data;
    if (!current) return;
    setName(current.name);
    setKind(current.kind);
    setEndpoint(current.endpoint ?? "");
    setAuthType(current.auth_type);
    setCredentialPolicy(current.credential_policy);
    setStatus(current.status);
    setGroupId(current.resource_group_id ?? "");
  }, [service.data]);

  const nameValid = name.trim().length > 0;
  const endpointValid = endpoint.trim().length > 0;
  const steps = [
    { key: "basics", label: "Basics", valid: nameValid },
    { key: "connection", label: "Connection", valid: endpointValid },
    { key: "placement", label: "Placement", valid: true },
    { key: "review", label: editing ? "Review + save" : "Review + create", valid: true },
  ];

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = {
        name: name.trim(),
        endpoint: endpoint.trim() || null,
        auth_type: authType,
        credential_policy: credentialPolicy,
        resource_group_id: groupId || null,
      };
      if (editing) {
        const saved = await api<Service>(`/v1/workspaces/${ws}/services/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ ...body, status }),
        });
        navigate(`/resources/service/${saved.id}`);
      } else {
        const created = await api<Service>(`/v1/workspaces/${ws}/services`, {
          method: "POST",
          body: JSON.stringify({ ...body, kind }),
        });
        navigate(`/resources/service/${created.id}`);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save the service");
    } finally {
      setBusy(false);
    }
  };

  const current = service.data;
  const groupName = groups.groups.find((group) => group.id === groupId)?.name;
  const kindTitle = SERVICE_KINDS.find((option) => option.value === kind)?.title ?? kind;

  return (
    <FormPage
      title={editing ? "Edit service" : "Create a service"}
      subtitle={editing ? `Service · ${current?.name ?? id}` : "Service · new"}
      crumbs={[
        { label: "Resource Manager" },
        { label: "All resources", to: "/resources" },
        ...(editing
          ? [
              { label: current?.name ?? "Service", to: id ? `/resources/service/${id}` : undefined },
              { label: "Edit" },
            ]
          : [{ label: "Create" }]),
      ]}
      steps={steps}
      current={step}
      onStep={setStep}
      editing={editing}
      onSubmit={submit}
      onCancel={() => navigate(id ? `/resources/service/${id}` : "/resources")}
      busy={busy}
      error={error}
    >
      {service.error ? <ErrorBox error={service.error} onRetry={service.reload} /> : null}
      {groups.error ? <ErrorBox error={groups.error} onRetry={groups.reload} /> : null}
      {editing && service.loading ? (
        <Skeleton rows={5} />
      ) : editing && !current ? (
        <div className="callout">
          This service does not exist. <Link to="/resources">Back to all resources</Link>.
        </div>
      ) : step === 0 ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (nameValid) setStep(1);
          }}
        >
          <FormIntro>
            A service is anything the gateway can mediate: an HTTP API with an OpenAPI
            document, an MCP server, or another agent. Discovery fills the tool catalog from
            the upstream definition.
          </FormIntro>
          <FormRow
            label="Service name"
            required
            error={touched.name && !nameValid ? "Cannot be empty" : undefined}
          >
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => setTouched((value) => ({ ...value, name: true }))}
              placeholder="tickets-api"
              autoFocus
              required
            />
          </FormRow>
          <FormRow label="Kind" hint={editing ? "The kind is fixed after creation." : undefined}>
            <ChoiceList
              name="service-kind"
              value={kind}
              options={SERVICE_KINDS}
              onChange={setKind}
              disabled={editing}
            />
          </FormRow>
        </form>
      ) : step === 1 ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (endpointValid) setStep(2);
          }}
        >
          <FormIntro>
            The gateway calls this endpoint on behalf of agents. Discovery reads the tool
            catalog from the same address.
          </FormIntro>
          <FormRow
            label="Endpoint"
            required
            error={touched.endpoint && !endpointValid ? "Cannot be empty" : undefined}
            hint={
              kind === "http"
                ? "Base URL. Discovery reads /openapi.json, /swagger.json or the URL itself."
                : kind === "mcp_http"
                  ? "Streamable HTTP endpoint of the MCP server."
                  : "Base URL of the remote agent."
            }
          >
            <input
              value={endpoint}
              onChange={(event) => setEndpoint(event.target.value)}
              onBlur={() => setTouched((value) => ({ ...value, endpoint: true }))}
              placeholder={
                kind === "http" ? "https://api.example.com" : "https://mcp.example.com/mcp"
              }
              required
            />
          </FormRow>
          <FormRow label="Authentication" hint="Discovery runs only with auth_type none.">
            <select value={authType} onChange={(event) => setAuthType(event.target.value)}>
              <option value="none">none</option>
              <option value="api_key">api_key</option>
              <option value="oauth2">oauth2</option>
              <option value="mtls">mtls</option>
            </select>
          </FormRow>
          <FormRow label="Credential policy">
            <select
              value={credentialPolicy}
              onChange={(event) => setCredentialPolicy(event.target.value)}
            >
              <option value="per_agent">per_agent</option>
              <option value="per_user">per_user</option>
              <option value="workspace">workspace</option>
            </select>
          </FormRow>
        </form>
      ) : step === 2 ? (
        <div>
          <FormIntro>
            Placement controls navigation and ownership. Access stays on grants.
          </FormIntro>
          <FormRow label="Resource group" hint="Leave empty to keep the service standalone.">
            <select value={groupId} onChange={(event) => setGroupId(event.target.value)}>
              <option value="">Standalone</option>
              {groups.groups.map((group) => (
                <option value={group.id} key={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
          </FormRow>
          {editing ? (
            <FormRow label="Status">
              <select value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="active">active</option>
                <option value="disabled">disabled</option>
              </select>
            </FormRow>
          ) : null}
        </div>
      ) : (
        <>
          <FormIntro>
            Check the values below. Discovery runs from the service page after creation.
          </FormIntro>
          <ReviewList
            items={[
              { label: "Name", value: name.trim() },
              { label: "Kind", value: kindTitle },
              { label: "Endpoint", value: <span className="mono">{endpoint.trim()}</span> },
              { label: "Authentication", value: authType },
              { label: "Credential policy", value: credentialPolicy },
              { label: "Resource group", value: groupName ?? "Standalone" },
              ...(editing ? [{ label: "Status", value: status }] : []),
            ]}
          />
        </>
      )}
    </FormPage>
  );
}

function AgentForm({ id }: { id?: string }) {
  const editing = Boolean(id);
  const ws = getWorkspace();
  const navigate = useNavigate();
  const groups = useGroups();
  const agent = useAsync<Agent | null>(
    () => (id ? api<Agent>(`/v1/workspaces/${ws}/agents/${id}`) : Promise.resolve(null)),
    [ws, id],
  );

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [kind, setKind] = useState("interactive");
  const [role, setRole] = useState("agent:executor");
  const [ceiling, setCeiling] = useState("{}");
  const [status, setStatus] = useState("active");
  const [groupId, setGroupId] = useState("");
  const [issueKey, setIssueKey] = useState(true);
  const [touched, setTouched] = useState({ name: false, slug: false });
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ id: string; apiKey: string | null } | null>(null);

  useEffect(() => {
    const current = agent.data;
    if (!current) return;
    setName(current.name);
    setSlug(current.slug);
    setKind(current.kind);
    setStatus(current.status);
    setCeiling(JSON.stringify(current.ceiling ?? {}, null, 2));
    setGroupId(current.resource_group_id ?? "");
  }, [agent.data]);

  const nameValid = name.trim().length > 0;
  const slugValid = /^[a-z0-9][a-z0-9-]*$/.test(slug.trim()) && slug.trim().length >= 2;
  const ceilingValid = parseObject(ceiling) !== null;
  const steps = [
    { key: "basics", label: "Basics", valid: nameValid && slugValid },
    { key: "access", label: "Access", valid: ceilingValid },
    { key: "review", label: editing ? "Review + save" : "Review + create", valid: true },
  ];

  const submit = async () => {
    setError(null);
    const parsedCeiling = parseObject(ceiling);
    if (parsedCeiling === null) {
      setError("Ceiling must be a valid JSON object.");
      setStep(1);
      return;
    }
    setBusy(true);
    try {
      if (editing) {
        await api<Agent>(`/v1/workspaces/${ws}/agents/${id}`, {
          method: "PATCH",
          body: JSON.stringify({
            name: name.trim(),
            slug: slug.trim(),
            kind,
            ceiling: parsedCeiling,
            status,
            resource_group_id: groupId || null,
          }),
        });
        navigate(`/resources/agent/${id}`);
      } else {
        const result = await api<{ agent: Agent; api_key: string | null; role: string }>(
          `/v1/workspaces/${ws}/agents`,
          {
            method: "POST",
            body: JSON.stringify({
              slug: slug.trim(),
              name: name.trim(),
              kind,
              role,
              ceiling: parsedCeiling,
              issue_credential: issueKey,
              resource_group_id: groupId || null,
            }),
          },
        );
        if (result.api_key) {
          setCreated({ id: result.agent.id, apiKey: result.api_key });
        } else {
          navigate(`/resources/agent/${result.agent.id}`);
        }
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save the agent");
    } finally {
      setBusy(false);
    }
  };

  const current = agent.data;
  const groupName = groups.groups.find((group) => group.id === groupId)?.name;
  const kindTitle = AGENT_KINDS.find((option) => option.value === kind)?.title ?? kind;

  if (created) {
    return (
      <Shell
        title="Agent created"
        subtitle="Agent · credentials"
        icon="agent"
        plain
        crumbs={[
          { label: "Resource Manager" },
          { label: "All resources", to: "/resources" },
          { label: name.trim() },
        ]}
      >
        <div className="panel form-panel">
          <div className="panel__header">
            <h2>API key</h2>
          </div>
          <div className="panel__body">
            <div className="callout callout--success">
              Copy this key now. The gateway stores only its hash. To issue another key later,
              open the agent and use Issue API key.
            </div>
            <pre className="code-block">{created.apiKey}</pre>
            <div className="form-actions">
              <Link className="btn" to="/resources">
                All resources
              </Link>
              <Link className="btn btn--primary" to={`/resources/agent/${created.id}`}>
                Open agent
              </Link>
            </div>
          </div>
        </div>
      </Shell>
    );
  }

  return (
    <FormPage
      title={editing ? "Edit agent" : "Create an agent"}
      subtitle={editing ? `Agent · ${current?.name ?? id}` : "Agent · new"}
      crumbs={[
        { label: "Resource Manager" },
        { label: "All resources", to: "/resources" },
        ...(editing
          ? [
              { label: current?.name ?? "Agent", to: id ? `/resources/agent/${id}` : undefined },
              { label: "Edit" },
            ]
          : [{ label: "Create" }]),
      ]}
      steps={steps}
      current={step}
      onStep={setStep}
      editing={editing}
      onSubmit={submit}
      onCancel={() => navigate(id ? `/resources/agent/${id}` : "/resources")}
      busy={busy}
      error={error}
    >
      {agent.error ? <ErrorBox error={agent.error} onRetry={agent.reload} /> : null}
      {groups.error ? <ErrorBox error={groups.error} onRetry={groups.reload} /> : null}
      {editing && agent.loading ? (
        <Skeleton rows={5} />
      ) : editing && !current ? (
        <div className="callout">
          This agent does not exist. <Link to="/resources">Back to all resources</Link>.
        </div>
      ) : step === 0 ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (nameValid && slugValid) setStep(1);
          }}
        >
          <FormIntro>
            An agent is an identity that calls tools through the gateway. The slug is part of
            its MCP URL; the ceiling caps what any grant may contain.
          </FormIntro>
          <FormRow
            label="Agent name"
            required
            error={touched.name && !nameValid ? "Cannot be empty" : undefined}
          >
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => setTouched((value) => ({ ...value, name: true }))}
              placeholder="Support Bot"
              autoFocus
              required
            />
          </FormRow>
          <FormRow
            label="Slug"
            required
            error={
              touched.slug && !slugValid
                ? "Use lowercase letters, digits and dashes, at least 2 characters."
                : undefined
            }
            hint={
              editing
                ? "Changing the slug changes the agent's MCP URL."
                : "Used in the MCP URL after creation."
            }
          >
            <input
              value={slug}
              onChange={(event) => setSlug(event.target.value.toLowerCase())}
              onBlur={() => setTouched((value) => ({ ...value, slug: true }))}
              placeholder="support-bot"
              pattern="[a-z0-9][a-z0-9-]*"
              required
            />
          </FormRow>
          <FormRow label="Kind">
            <ChoiceList name="agent-kind" value={kind} options={AGENT_KINDS} onChange={setKind} />
          </FormRow>
        </form>
      ) : step === 1 ? (
        <div>
          <FormIntro>
            Access settings are enforced on every call. Grants can narrow the ceiling but
            never exceed it.
          </FormIntro>
          <FormRow label={editing ? "Status" : "Role"}>
            {editing ? (
              <select value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="active">active</option>
                <option value="suspended">suspended</option>
                <option value="revoked">revoked</option>
              </select>
            ) : (
              <select value={role} onChange={(event) => setRole(event.target.value)}>
                <option value="agent:executor">agent:executor</option>
                <option value="agent:admin">agent:admin</option>
              </select>
            )}
          </FormRow>
          <FormRow label="Resource group" hint="Leave empty to keep the agent standalone.">
            <select value={groupId} onChange={(event) => setGroupId(event.target.value)}>
              <option value="">Standalone</option>
              {groups.groups.map((group) => (
                <option value={group.id} key={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
          </FormRow>
          {!editing ? (
            <FormRow label="Credential" hint="Issued once, shown after creation.">
              <label className="check-inline">
                <input
                  type="checkbox"
                  checked={issueKey}
                  onChange={(event) => setIssueKey(event.target.checked)}
                />
                Issue an API key on creation
              </label>
            </FormRow>
          ) : null}
          <FormRow
            label="Ceiling"
            hint='JSON object. Example: {"services": {"<service-id>": {"tools": ["get_ticket"]}}}'
            error={!ceilingValid ? "Ceiling must be a valid JSON object." : undefined}
          >
            <textarea
              value={ceiling}
              onChange={(event) => setCeiling(event.target.value)}
              rows={10}
              className="mono"
              spellCheck={false}
            />
          </FormRow>
        </div>
      ) : (
        <>
          <FormIntro>Check the values below before saving the agent.</FormIntro>
          <ReviewList
            items={[
              { label: "Name", value: name.trim() },
              { label: "Slug", value: <span className="mono">{slug.trim()}</span> },
              { label: "Kind", value: kindTitle },
              editing
                ? { label: "Status", value: status }
                : { label: "Role", value: role },
              { label: "Resource group", value: groupName ?? "Standalone" },
              {
                label: "Credential",
                value: editing ? "Managed from the agent page" : issueKey ? "Issued on create" : "None",
              },
              {
                label: "Ceiling",
                value: <pre className="code-block">{ceiling.trim() || "{}"}</pre>,
              },
            ]}
          />
        </>
      )}
    </FormPage>
  );
}

function parseObject(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value.trim() || "{}");
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}
