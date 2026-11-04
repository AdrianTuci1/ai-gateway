import { useState, type ReactNode } from "react";

import { Icon } from "./Icon";
import { Empty } from "./ui";

export type Column<T> = {
  key: string;
  header: string;
  width?: string;
  align?: "right";
  truncate?: boolean;
  render: (row: T) => ReactNode;
};

export type TableRow<T> = {
  key: string;
  data: T;
  children?: ReactNode;
  nestedTitle?: string;
};

type Props<T> = {
  columns: Column<T>[];
  rows: TableRow<T>[];
  empty?: string;
  emptyAction?: ReactNode;
  onRowClick?: (row: T) => void;
  defaultExpanded?: string[];
};

export function DataTable<T>({
  columns,
  rows,
  empty = "Nothing here yet.",
  emptyAction,
  onRowClick,
  defaultExpanded = [],
}: Props<T>) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(defaultExpanded));
  const expandable = rows.some((row) => row.children !== undefined);

  const toggle = (key: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (rows.length === 0) {
    return <Empty title={empty} action={emptyAction} />;
  }

  return (
    <div className="table-wrap">
      <table className="grid-table">
        <thead>
          <tr>
            {expandable ? <th className="cell-narrow" aria-label="Expand" /> : null}
            {columns.map((column) => (
              <th
                key={column.key}
                style={column.width ? { width: column.width } : undefined}
                className={column.align === "right" ? "cell-num" : undefined}
                scope="col"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isOpen = expanded.has(row.key);
            return (
              <RowGroup
                key={row.key}
                row={row}
                isOpen={isOpen}
                expandable={expandable}
                columns={columns}
                onToggle={() => toggle(row.key)}
                onRowClick={onRowClick}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RowGroup<T>({
  row,
  isOpen,
  expandable,
  columns,
  onToggle,
  onRowClick,
}: {
  row: TableRow<T>;
  isOpen: boolean;
  expandable: boolean;
  columns: Column<T>[];
  onToggle: () => void;
  onRowClick?: (row: T) => void;
}) {
  return (
    <>
      <tr
        className={isOpen ? "is-active" : undefined}
        onClick={onRowClick ? () => onRowClick(row.data) : undefined}
        style={onRowClick ? { cursor: "pointer" } : undefined}
      >
        {expandable ? (
          <td className="cell-narrow">
            {row.children !== undefined ? (
              <button
                className="expander"
                type="button"
                aria-expanded={isOpen}
                aria-label={isOpen ? "Collapse" : "Expand"}
                onClick={(event) => {
                  event.stopPropagation();
                  onToggle();
                }}
              >
                <Icon name={isOpen ? "chevronDown" : "chevron"} size={12} />
              </button>
            ) : null}
          </td>
        ) : null}
        {columns.map((column) => (
          <td
            key={column.key}
            className={[column.align === "right" ? "cell-num" : "", column.truncate ? "cell-truncate" : ""]
              .filter(Boolean)
              .join(" ")}
          >
            {column.render(row.data)}
          </td>
        ))}
      </tr>
      {isOpen && row.children !== undefined ? (
        <tr className="nested-row">
          <td colSpan={columns.length + (expandable ? 1 : 0)}>
            <div className="nested">
              {row.nestedTitle ? <div className="nested__title">{row.nestedTitle}</div> : null}
              {row.children}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
