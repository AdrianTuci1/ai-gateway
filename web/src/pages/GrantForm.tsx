import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  ApiError,
  api,
  getWorkspace,
  type Agent,
  type Grant,
  type Service,
  type Tool,
} from "../api";
import {
  FormIntro,
  FormPage,
  FormRow,
  ReviewList,
} from "../components/FormPage";
import { ErrorBox, Skeleton } from "../components/ui";
import { useAsync } from "../hooks";

function toLocalInput(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
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

export function GrantForm() {
  const { id, serviceId } = useParams();
  const [params] = useSearchParams();
  const editing = Boolean(serviceId);
  const ws = getWorkspace();
  const navigate = useNavigate();

  const agent = useAsync<Agent | null>(
    () => (id ? api<Agent>(`/v1/workspaces/${ws}/agents/${id}`) : Promise.resolve(null)),
    [ws, id],
  );
  const services = useAsync(
    () => api<Service[]>(`/v1/workspaces/${ws}/services`).catch(() => []),
    [ws],
  );
  const grants = useAsync<Grant[]>(
    () =>
      id
        ? api<Grant[]>(`/v1/workspaces/${ws}/agents/${id}/grants`).catch(() => [])
        : Promise.resolve([]),
    [ws, id],
  );

  const [selectedService, setSelectedService] = useState(serviceId ?? params.get("service") ?? "");
  const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set());
  const [constraints, setConstraints] = useState("{}");
  const [expires, setExpires] = useState("");
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const initialized = useRef(false);

  const tools = useAsync<Tool[]>(
    () =>
      selectedService
        ? api<Tool[]>(`/v1/workspaces/${ws}/services/${selectedService}/tools`).catch(() => [])
        : Promise.resolve([]),
    [ws, selectedService],
  );

  useEffect(() => {
    if (!editing || initialized.current) return;
    const grant = (grants.data ?? []).find((entry) => entry.service_id === serviceId);
    if (!grant) return;
    initialized.current = true;
    setSelectedTools(new Set(grant.tools));
    setConstraints(JSON.stringify(grant.arg_constraints ?? {}, null, 2));
    setExpires(toLocalInput(grant.expires_at));
  }, [editing, grants.data, serviceId]);

  const serviceName =
    services.data?.find((service) => service.id === selectedService)?.name ?? selectedService;
  const constraintsValid = parseObject(constraints) !== null;

  const steps = [
    { key: "scope", label: "Scope", valid: Boolean(selectedService) },
    { key: "tools", label: "Tools", valid: selectedTools.size > 0 },
    { key: "constraints", label: "Constraints", valid: constraintsValid },
    { key: "review", label: editing ? "Review + save" : "Review + create", valid: true },
  ];

  const toggleTool = (name: string) => {
    setSelectedTools((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const discover = async () => {
    if (!selectedService) return;
    setDiscovering(true);
    setError(null);
    try {
      await api(`/v1/workspaces/${ws}/services/${selectedService}/discover`, { method: "POST" });
      tools.reload();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Discovery failed");
    } finally {
      setDiscovering(false);
    }
  };

  const submit = async () => {
    if (!id || !selectedService) return;
    setError(null);
    const parsed = parseObject(constraints);
    if (parsed === null) {
      setError("Argument constraints must be a valid JSON object.");
      setStep(2);
      return;
    }
    setBusy(true);
    try {
      await api<Grant>(`/v1/workspaces/${ws}/agents/${id}/grants/${selectedService}`, {
        method: "PUT",
        body: JSON.stringify({
          tools: Array.from(selectedTools).sort(),
          arg_constraints: parsed,
          expires_at: expires ? new Date(expires).toISOString() : null,
        }),
      });
      navigate(`/resources/agent/${id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save the grant");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!id || !selectedService) return;
    if (!window.confirm(`Revoke the grant on “${serviceName}”? Calls will be denied immediately.`)) {
      return;
    }
    setBusy(true);
    try {
      await api(`/v1/workspaces/${ws}/agents/${id}/grants/${selectedService}`, {
        method: "DELETE",
      });
      navigate(`/resources/agent/${id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not revoke the grant");
    } finally {
      setBusy(false);
    }
  };

  const catalog = tools.data ?? [];
  const allSelected = catalog.length > 0 && selectedTools.size === catalog.length;

  return (
    <FormPage
      title={editing ? "Edit grant" : "New grant"}
      subtitle={agent.data ? `Grant · ${agent.data.name}` : "Grant · new"}
      crumbs={[
        { label: "Resource Manager" },
        { label: "All resources", to: "/resources" },
        { label: agent.data?.name ?? "Agent", to: id ? `/resources/agent/${id}` : undefined },
        { label: "Grants", to: id ? `/resources/agent/${id}` : undefined },
        { label: editing ? "Edit" : "New" },
      ]}
      steps={steps}
      current={step}
      onStep={setStep}
      editing={editing}
      onSubmit={submit}
      onCancel={() => navigate(id ? `/resources/agent/${id}` : "/grants")}
      busy={busy}
      error={error}
      extraFooter={
        editing ? (
          <button className="btn btn--danger" type="button" onClick={remove} disabled={busy}>
            Revoke grant
          </button>
        ) : undefined
      }
    >
      {agent.error ? <ErrorBox error={agent.error} onRetry={agent.reload} /> : null}
      {services.error ? <ErrorBox error={services.error} onRetry={services.reload} /> : null}
      {!id ? (
        <div className="callout">
          Choose an agent first. <Link to="/grants">Back to policies</Link>.
        </div>
      ) : agent.loading ? (
        <Skeleton rows={5} />
      ) : step === 0 ? (
        <div>
          <FormIntro>
            A grant allows one agent to call a set of tools on one service. Calls are denied
            until a matching grant exists.
          </FormIntro>
          <FormRow label="Agent">
            <input value={agent.data?.name ?? ""} readOnly disabled />
          </FormRow>
          <FormRow
            label="Service"
            required
            hint={editing ? "The service is fixed for this grant." : undefined}
          >
            <select
              value={selectedService}
              onChange={(event) => {
                setSelectedService(event.target.value);
                setSelectedTools(new Set());
                setConstraints("{}");
                setExpires("");
              }}
              disabled={editing}
              required
            >
              <option value="">Select a service</option>
              {(services.data ?? []).map((service) => (
                <option value={service.id} key={service.id}>
                  {service.name} · {service.kind}
                </option>
              ))}
            </select>
          </FormRow>
        </div>
      ) : step === 1 ? (
        <div>
          <FormIntro>
            Select the tools this agent may call. The list comes from the service catalog;
            run discovery if it is empty.
          </FormIntro>
          {!selectedService ? (
            <p className="muted small">Select a service in the Scope step first.</p>
          ) : tools.loading ? (
            <Skeleton rows={4} />
          ) : catalog.length === 0 ? (
            <div className="callout">
              <div className="row row--between">
                <span>No tools in the catalog for this service. Run discovery first.</span>
                <button
                  className="btn btn--small"
                  type="button"
                  onClick={discover}
                  disabled={discovering}
                >
                  {discovering ? "Discovering…" : "Discover tools"}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="form-toolbar">
                <span className="muted small">
                  {selectedTools.size} of {catalog.length} tools selected
                </span>
                <button
                  className="link-button"
                  type="button"
                  onClick={() =>
                    setSelectedTools(
                      allSelected ? new Set() : new Set(catalog.map((tool) => tool.name)),
                    )
                  }
                >
                  {allSelected ? "clear all" : "select all"}
                </button>
              </div>
              <div className="check-list">
                {catalog.map((tool) => (
                  <label className="check-row" key={tool.id}>
                    <input
                      type="checkbox"
                      checked={selectedTools.has(tool.name)}
                      onChange={() => toggleTool(tool.name)}
                    />
                    <span className="check-row__main">
                      <span className="mono">{tool.name}</span>
                      <span className="muted small">{tool.description ?? "No description"}</span>
                    </span>
                  </label>
                ))}
              </div>
            </>
          )}
        </div>
      ) : step === 2 ? (
        <div>
          <FormIntro>
            Constraints narrow how a tool may be called. Leave the object empty to allow the
            tool with its catalog schema unchanged.
          </FormIntro>
          <FormRow
            label="Argument constraints"
            hint='JSON object keyed by tool, for example {"get_ticket": {"id": {"max_length": 64}}}.'
            error={!constraintsValid ? "Must be a valid JSON object." : undefined}
          >
            <textarea
              value={constraints}
              onChange={(event) => setConstraints(event.target.value)}
              rows={10}
              className="mono"
              spellCheck={false}
            />
          </FormRow>
          <FormRow label="Expires" hint="Leave empty for a grant with no expiry.">
            <input
              type="datetime-local"
              value={expires}
              onChange={(event) => setExpires(event.target.value)}
            />
          </FormRow>
        </div>
      ) : (
        <>
          <FormIntro>Check the grant before saving it.</FormIntro>
          <ReviewList
            items={[
              { label: "Agent", value: agent.data?.name ?? id },
              { label: "Service", value: serviceName || "—" },
              {
                label: "Tools",
                value: (
                  <span className="tag-list">
                    {Array.from(selectedTools)
                      .sort()
                      .map((tool) => (
                        <span className="tag" key={tool}>
                          {tool}
                        </span>
                      ))}
                  </span>
                ),
              },
              {
                label: "Argument constraints",
                value: <pre className="code-block">{constraints.trim() || "{}"}</pre>,
              },
              { label: "Expires", value: expires ? new Date(expires).toLocaleString() : "never" },
            ]}
          />
        </>
      )}
    </FormPage>
  );
}
