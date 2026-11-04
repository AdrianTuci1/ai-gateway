import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api, getWorkspace, type Inventory, type ResourceGroup } from "../api";
import {
  ChoiceList,
  FormIntro,
  FormPage,
  FormRow,
  ReviewList,
} from "../components/FormPage";
import { ErrorBox, Skeleton } from "../components/ui";
import { useAsync } from "../hooks";

const KIND_OPTIONS = [
  {
    value: "application",
    title: "Application",
    description: "A workload owned by one product team.",
  },
  {
    value: "platform",
    title: "Platform",
    description: "Shared infrastructure that other groups consume.",
  },
  {
    value: "workload",
    title: "Workload",
    description: "A service and the agents that operate it.",
  },
];

export function GroupForm() {
  const { id } = useParams();
  const editing = Boolean(id);
  const ws = getWorkspace();
  const navigate = useNavigate();
  const inventory = useAsync(() => api<Inventory>(`/v1/workspaces/${ws}/inventory`), [ws]);
  const existing = id ? inventory.data?.groups.find((group) => group.id === id) : undefined;

  const [name, setName] = useState("");
  const [kind, setKind] = useState("application");
  const [description, setDescription] = useState("");
  const [touched, setTouched] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!existing) return;
    setName(existing.name);
    setKind(existing.kind);
    setDescription(existing.description ?? "");
  }, [existing]);

  const nameValid = name.trim().length > 0;
  const steps = [
    { key: "basics", label: "Basics", valid: nameValid },
    { key: "review", label: editing ? "Review + save" : "Review + create", valid: true },
  ];

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = {
        name: name.trim(),
        kind,
        description: description.trim() || null,
      };
      const group = editing
        ? await api<ResourceGroup>(`/v1/workspaces/${ws}/resource-groups/${id}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          })
        : await api<ResourceGroup>(`/v1/workspaces/${ws}/resource-groups`, {
            method: "POST",
            body: JSON.stringify(body),
          });
      navigate(`/groups/${group.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save the group");
    } finally {
      setBusy(false);
    }
  };

  return (
    <FormPage
      title={editing ? "Edit resource group" : "Create a resource group"}
      subtitle={editing ? "Resource group · existing" : "Resource group · new"}
      crumbs={[
        { label: "Resource Manager" },
        { label: "Resource groups", to: "/groups" },
        ...(editing
          ? [
              { label: existing?.name ?? "Resource group", to: id ? `/groups/${id}` : undefined },
              { label: "Edit" },
            ]
          : [{ label: "Create" }]),
      ]}
      steps={steps}
      current={step}
      onStep={setStep}
      editing={editing}
      onSubmit={submit}
      onCancel={() => navigate(editing && id ? `/groups/${id}` : "/groups")}
      busy={busy}
      error={error}
    >
      {inventory.error ? <ErrorBox error={inventory.error} onRetry={inventory.reload} /> : null}
      {inventory.loading && editing ? (
        <Skeleton rows={5} />
      ) : editing && !existing ? (
        <div className="callout">
          This resource group does not exist. <Link to="/groups">Back to resource groups</Link>.
        </div>
      ) : step === 0 ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (nameValid) setStep(1);
          }}
        >
          <FormIntro>
            A resource group is a container for services and agents. Resources can also stay
            standalone; grouping changes navigation and ownership, never the policy itself.
          </FormIntro>
          <FormRow
            label="Resource group name"
            required
            error={touched && !nameValid ? "Cannot be empty" : undefined}
          >
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => setTouched(true)}
              placeholder="customer-support"
              autoFocus
              required
            />
          </FormRow>
          <FormRow label="Kind" hint="Used for grouping and sorting in the resource list.">
            <ChoiceList name="group-kind" value={kind} options={KIND_OPTIONS} onChange={setKind} />
          </FormRow>
          <FormRow label="Description" hint="Optional. Shown on the group overview.">
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={4}
            />
          </FormRow>
        </form>
      ) : (
        <>
          <FormIntro>
            Check the values below. You can jump back to any step from the tabs above.
          </FormIntro>
          <ReviewList
            items={[
              { label: "Name", value: name.trim() },
              {
                label: "Kind",
                value: KIND_OPTIONS.find((option) => option.value === kind)?.title ?? kind,
              },
              { label: "Description", value: description.trim() },
            ]}
          />
        </>
      )}
    </FormPage>
  );
}
