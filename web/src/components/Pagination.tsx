import { Icon } from "./Icon";

type Props = {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  disabled?: boolean;
};

type Token = number | "ellipsis";

export function Pagination({ page, pageSize, total, onPage, disabled = false }: Props) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(Math.max(page, 1), pageCount);
  const first = total === 0 ? 0 : (current - 1) * pageSize + 1;
  const last = Math.min(current * pageSize, total);

  return (
    <nav className="pager" aria-label="Pagination">
      <span className="pager__meta">
        {total === 0 ? "No results" : `${first}–${last} of ${total}`}
      </span>
      <div className="pager__controls">
        <button
          className="pager__btn"
          type="button"
          title="Previous page"
          aria-label="Previous page"
          onClick={() => onPage(current - 1)}
          disabled={disabled || current <= 1}
        >
          <Icon name="chevron" size={12} className="pager__prev" />
        </button>
        {pageTokens(current, pageCount).map((token, index) =>
          token === "ellipsis" ? (
            <span className="pager__ellipsis" key={`ellipsis-${index}`}>
              …
            </span>
          ) : (
            <button
              className={`pager__btn${token === current ? " is-active" : ""}`}
              type="button"
              key={token}
              aria-label={`Page ${token}`}
              aria-current={token === current ? "page" : undefined}
              onClick={() => onPage(token)}
              disabled={disabled}
            >
              {token}
            </button>
          ),
        )}
        <button
          className="pager__btn"
          type="button"
          title="Next page"
          aria-label="Next page"
          onClick={() => onPage(current + 1)}
          disabled={disabled || current >= pageCount}
        >
          <Icon name="chevron" size={12} />
        </button>
      </div>
    </nav>
  );
}

function pageTokens(current: number, total: number): Token[] {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  const tokens: Token[] = [1];
  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  if (start > 2) tokens.push("ellipsis");
  for (let page = start; page <= end; page += 1) tokens.push(page);
  if (end < total - 1) tokens.push("ellipsis");
  tokens.push(total);
  return tokens;
}
