import type { ReactNode } from "react";

import { Shell, type Crumb, type Tab } from "./Shell";

export type FormStep = {
  key: string;
  label: string;
  valid: boolean;
};

type FormPageProps = {
  title: string;
  subtitle?: string;
  crumbs: Crumb[];
  steps: FormStep[];
  current: number;
  onStep: (index: number) => void;
  editing: boolean;
  onSubmit: () => void;
  onCancel: () => void;
  busy: boolean;
  error?: string | null;
  extraFooter?: ReactNode;
  children: ReactNode;
};

export function FormPage({
  title,
  subtitle,
  crumbs,
  steps,
  current,
  onStep,
  editing,
  onSubmit,
  onCancel,
  busy,
  error,
  extraFooter,
  children,
}: FormPageProps) {
  const last = steps.length - 1;
  const active = steps[current];
  const allValid = steps.every((step) => step.valid);
  const tabs: Tab[] = steps.map((step, index) => ({
    label: step.label,
    to: `#${step.key}`,
    status: index <= current && !step.valid ? "error" : undefined,
    onClick: () => onStep(index),
  }));

  const footer = (
    <>
      {current > 0 ? (
        <button className="btn" type="button" onClick={() => onStep(current - 1)}>
          Previous
        </button>
      ) : null}
      {current < last ? (
        <>
          <button
            className="btn"
            type="button"
            disabled={!active.valid}
            onClick={() => onStep(current + 1)}
          >
            Next
          </button>
          <button className="btn btn--primary" type="button" onClick={() => onStep(last)}>
            Review + {editing ? "save" : "create"}
          </button>
        </>
      ) : (
        <button
          className="btn btn--primary"
          type="button"
          disabled={!allValid || busy}
          onClick={onSubmit}
        >
          {busy ? "Saving…" : editing ? "Save" : "Create"}
        </button>
      )}
      <span className="form-footer__spacer" />
      {extraFooter}
      <button className="btn" type="button" onClick={onCancel}>
        Cancel
      </button>
    </>
  );

  return (
    <Shell
      title={title}
      subtitle={subtitle}
      crumbs={crumbs}
      tabs={tabs}
      activeTab={`#${active.key}`}
      plain
      footer={footer}
    >
      <div className="form-body">
        {children}
        {error ? <div className="callout callout--error">{error}</div> : null}
      </div>
    </Shell>
  );
}

export function FormIntro({ children }: { children: ReactNode }) {
  return <p className="form-intro">{children}</p>;
}

export function FormRow({
  label,
  required,
  hint,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="form-row">
      <div className="form-row__label">
        {label}
        {required ? <span className="form-row__required"> *</span> : null}
      </div>
      <div className="form-row__control">
        {children}
        {error ? <span className="field__error">{error}</span> : null}
        {hint ? <span className="field__hint">{hint}</span> : null}
      </div>
    </div>
  );
}

export type Choice = {
  value: string;
  title: string;
  description?: string;
};

export function ChoiceList({
  name,
  value,
  options,
  onChange,
  disabled = false,
}: {
  name: string;
  value: string;
  options: Choice[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="choice-list">
      {options.map((option) => (
        <label className="choice" key={option.value}>
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
            disabled={disabled}
          />
          <span className="choice__text">
            <strong>{option.title}</strong>
            {option.description ? <span>{option.description}</span> : null}
          </span>
        </label>
      ))}
    </div>
  );
}

export type ReviewItem = {
  label: string;
  value: ReactNode;
};

export function ReviewList({ items }: { items: ReviewItem[] }) {
  return (
    <div className="review-list">
      {items.map((item) => (
        <div className="review-row" key={item.label}>
          <span className="review-row__label">{item.label}</span>
          <span className="review-row__value">{item.value || <span className="muted">—</span>}</span>
        </div>
      ))}
    </div>
  );
}
