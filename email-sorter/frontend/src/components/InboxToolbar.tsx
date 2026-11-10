import {
  Check,
  ChevronDown,
  Loader2,
  MoreHorizontal,
  Search,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";

import type { SortOrder, WindowDays } from "../domain/email";
import { CATEGORY_KEYS, CONTENT_CATEGORIES } from "../domain/taxonomy";
import type { InboxView } from "../hooks/useInboxView";
import { Popover } from "./Popover";

const WINDOWS: readonly { value: WindowDays; label: string }[] = [
  { value: 1, label: "24 hours" },
  { value: 7, label: "7 days" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
  { value: 0, label: "All mail" },
  { value: "custom", label: "Custom…" },
];

const SELECT =
  "h-11 w-full appearance-none rounded-[10px] border border-line bg-surface pr-8 pl-3 text-[14px] font-medium text-ink shadow-[0_1px_2px_rgba(0,0,0,0.03)] focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none";

const BUTTON =
  "inline-flex min-h-11 shrink-0 items-center justify-center gap-1.5 rounded-[10px] px-4 text-[14px] font-semibold transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60";

const MENU_ITEM =
  "flex min-h-11 w-full items-center rounded-lg px-2.5 text-left text-[14px] text-ink hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:opacity-50";

function SelectBox({
  id,
  label,
  value,
  onChange,
  children,
  className = "",
}: {
  id: string;
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={SELECT}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute top-1/2 right-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted"
        aria-hidden="true"
      />
    </div>
  );
}

function PrimaryAction({ view }: { view: InboxView }) {
  const { loading, classifying, progress, hasLoaded, total, classifiedCount } = view;
  const unclassified = total - classifiedCount;

  // While mail loads, show only that: no sort button, no progress, no cancel.
  if (loading || view.receiving) {
    return (
      <span
        role="status"
        aria-live="polite"
        className="inline-flex min-h-11 items-center gap-2 text-[13px] text-muted"
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Loading mail…
      </span>
    );
  }

  // Background sorting is not a decision for the student: show quiet progress.
  if (classifying && view.autoRun) {
    return (
      <span
        role="status"
        aria-live="polite"
        className="inline-flex min-h-11 items-center gap-2 text-[13px] text-muted tabular-nums"
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Sorting {progress?.done}/{progress?.total}
        <button
          type="button"
          onClick={view.cancel}
          className="min-h-11 rounded-lg px-1.5 font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        >
          Stop
        </button>
      </span>
    );
  }

  if (classifying) {
    return (
      <button
        type="button"
        onClick={view.cancel}
        className={`${BUTTON} border border-line bg-surface text-ink hover:bg-surface-muted`}
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {progress ? `Classifying ${progress.done}/${progress.total}` : "Loading…"}
        <span className="text-muted">· Cancel</span>
      </button>
    );
  }

  if (!hasLoaded) {
    return (
      <button
        type="button"
        onClick={() => void view.load({ announce: true })}
        className={`${BUTTON} bg-accent text-white hover:bg-accent-dark`}
      >
        Load emails
      </button>
    );
  }

  const healthy = view.health?.ready !== false;
  const sortsByItself = view.autoSort && !view.autoPaused && healthy && !view.waitingForBatch;

  if (unclassified > 0 && !sortsByItself) {
    return (
      <button
        type="button"
        onClick={() => void view.classifyPending()}
        className={`${BUTTON} bg-accent text-white hover:bg-accent-dark`}
      >
        <Sparkles className="h-4 w-4" aria-hidden="true" />
        Sort {unclassified} email{unclassified === 1 ? "" : "s"}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void view.load({ announce: true })}
      className={`${BUTTON} border border-line bg-surface text-ink hover:bg-surface-muted max-sm:hidden`}
    >
      Check for new mail
    </button>
  );
}

function OptionsMenu({ view, className = "" }: { view: InboxView; className?: string }) {
  const { session, backends, backend, health, hasLoaded, classifiedCount } = view;
  const busy = view.loading || view.classifying;

  return (
    <div className={className}>
    <Popover
      ariaLabel="More options"
      align="right"
      buttonClassName="w-11 justify-center px-0"
      label={<MoreHorizontal className="h-4 w-4" aria-hidden="true" />}
    >
      <div className="flex flex-col gap-1">
        {backends.length > 0 ? (
          <div className="px-1 pb-2">
            <label htmlFor="inbox-model" className="text-[12px] font-medium text-muted">
              Sorting model
            </label>
            <select
              id="inbox-model"
              value={backend}
              onChange={(event) => view.setBackend(event.target.value)}
              className="mt-1 h-11 w-full rounded-[10px] border border-line bg-surface px-3 text-[14px] text-ink focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
            >
              {backends.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                  {item.ready === false ? " (not ready)" : ""}
                </option>
              ))}
            </select>
            {health && health.ready === false ? (
              <p role="status" className="mt-1.5 text-[13px] text-action-now-fg">
                {health.detail}
              </p>
            ) : null}
          </div>
        ) : null}

        <button
          type="button"
          role="switch"
          aria-checked={view.autoSort}
          className={`${MENU_ITEM} justify-between gap-3`}
          onClick={() => view.setAutoSort(!view.autoSort)}
        >
          Sort new mail automatically
          <span
            aria-hidden="true"
            className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
              view.autoSort ? "bg-accent" : "bg-line"
            }`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
                view.autoSort ? "left-[18px]" : "left-0.5"
              }`}
            />
          </span>
        </button>

        <button
          type="button"
          className={MENU_ITEM}
          disabled={busy}
          onClick={() => void view.load({ announce: true })}
        >
          Reload emails
        </button>

        {hasLoaded && classifiedCount > 0 ? (
          <button
            type="button"
            className={MENU_ITEM}
            disabled={busy}
            onClick={() => void view.classifyAll()}
          >
            Sort all again
          </button>
        ) : null}

        {session.provider === "outlook" ? (
          <button type="button" className={MENU_ITEM} onClick={view.openTokenDialog}>
            {view.token ? "Change Outlook token" : "Add Outlook token"}
          </button>
        ) : null}
      </div>
    </Popover>
    </div>
  );
}

function CategoryList({ view }: { view: InboxView }) {
  return (
    <ul className="flex flex-col gap-0.5">
      {CATEGORY_KEYS.map((key) => {
        const checked = view.categories.includes(key);

        return (
          <li key={key}>
            <button
              type="button"
              role="checkbox"
              aria-checked={checked}
              onClick={() => view.toggleCategory(key)}
              className={`${MENU_ITEM} gap-2.5`}
            >
              <span
                className={`grid h-4.5 w-4.5 shrink-0 place-items-center rounded border ${
                  checked ? "border-accent bg-accent text-white" : "border-line"
                }`}
                aria-hidden="true"
              >
                {checked ? <Check className="h-3 w-3" /> : null}
              </span>
              {CONTENT_CATEGORIES[key]}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function CategoryFilter({ view, className = "" }: { view: InboxView; className?: string }) {
  const count = view.categories.length;

  return (
    <div className={className}>
    <Popover
      ariaLabel="Filter by category"
      active={count > 0}
      label={
        <>
          Category
          {count > 0 ? (
            <span className="rounded-full bg-accent px-1.5 text-[12px] font-semibold text-white tabular-nums">
              {count}
            </span>
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-muted" aria-hidden="true" />
          )}
        </>
      }
    >
      <CategoryList view={view} />
    </Popover>
    </div>
  );
}

function FiltersSheet({ view, className = "" }: { view: InboxView; className?: string }) {
  const active = view.categories.length + (view.sort !== "newest" ? 1 : 0);

  return (
    <div className={className}>
      <Popover
        ariaLabel="Filters"
        active={active > 0}
        label={
          <>
            <SlidersHorizontal className="h-4 w-4 text-muted" aria-hidden="true" />
            Filters
            {active > 0 ? (
              <span className="rounded-full bg-accent px-1.5 text-[12px] font-semibold text-white tabular-nums">
                {active}
              </span>
            ) : null}
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <div>
            <p className="mb-1 text-[12px] font-medium text-muted">Show mail from</p>
            <SelectBox
              id="inbox-window-sheet"
              label="Show mail from"
              value={view.windowDays}
              onChange={(value) =>
                view.setWindowDays(value === "custom" ? "custom" : (Number(value) as WindowDays))
              }
            >
              {WINDOWS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </SelectBox>
          </div>
          <div>
            <p className="mb-1 text-[12px] font-medium text-muted">Sort</p>
            <SelectBox
              id="inbox-sort-sheet"
              label="Sort"
              value={view.sort}
              onChange={(value) => view.setSort(value as SortOrder)}
            >
              <option value="newest">Newest</option>
              <option value="oldest">Oldest</option>
            </SelectBox>
          </div>
          <div>
            <p className="mb-1 text-[12px] font-medium text-muted">Category</p>
            <CategoryList view={view} />
          </div>
        </div>
      </Popover>
    </div>
  );
}

export function InboxToolbar({ view }: { view: InboxView }) {
  return (
    <section aria-label="Search, filter and sort mail" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative order-1 min-w-0 flex-1 basis-[calc(100%-56px)] sm:basis-[240px]">
          <label htmlFor="inbox-search" className="sr-only">
            Search
          </label>
          <Search
            className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted"
            aria-hidden="true"
          />
          <input
            id="inbox-search"
            type="search"
            value={view.query}
            onChange={(event) => view.setQuery(event.target.value)}
            placeholder="Search sender or subject"
            autoComplete="off"
            spellCheck={false}
            className="h-11 w-full rounded-[10px] border border-line bg-surface pr-11 pl-9 text-[14px] text-ink shadow-[0_1px_2px_rgba(0,0,0,0.03)] placeholder:text-muted/70 focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none [&::-webkit-search-cancel-button]:hidden"
          />
          {view.query ? (
            <button
              type="button"
              onClick={() => view.setQuery("")}
              aria-label="Clear search"
              className="absolute top-0 right-0 grid h-11 w-11 place-items-center rounded-md text-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          ) : null}
        </div>

        {/* On phones the options button sits beside search; on wide screens it moves to the far right. */}
        <OptionsMenu view={view} className="order-2 sm:order-6 sm:ml-auto" />

        <SelectBox
          id="inbox-window"
          label="Show mail from"
          value={view.windowDays}
          onChange={(value) =>
            view.setWindowDays(
              value === "custom" ? "custom" : (Number(value) as WindowDays),
            )
          }
          className="order-3 min-w-[104px] flex-1 max-sm:hidden sm:w-[132px] sm:flex-none"
        >
          {WINDOWS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </SelectBox>

        <CategoryFilter view={view} className="order-4 shrink-0 max-sm:hidden" />
        <FiltersSheet view={view} className="order-3 shrink-0 sm:hidden" />

        <SelectBox
          id="inbox-sort"
          label="Sort"
          value={view.sort}
          onChange={(value) => view.setSort(value as SortOrder)}
          className="order-5 w-[104px] shrink-0 max-sm:hidden sm:w-[116px]"
        >
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
        </SelectBox>

        <div className="order-7 max-sm:flex-1 max-sm:[&>*]:w-full">
          <PrimaryAction view={view} />
        </div>
      </div>

      {view.windowDays === "custom" ? (
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-[13px] font-medium text-muted">
            From
            <input
              type="date"
              value={view.range.since}
              max={view.range.before || undefined}
              onChange={(event) =>
                view.setRange({ ...view.range, since: event.target.value })
              }
              className="h-11 rounded-[10px] border border-line bg-surface px-2.5 text-[14px] text-ink focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
            />
          </label>
          <label className="flex items-center gap-2 text-[13px] font-medium text-muted">
            To
            <input
              type="date"
              value={view.range.before}
              min={view.range.since || undefined}
              onChange={(event) =>
                view.setRange({ ...view.range, before: event.target.value })
              }
              className="h-11 rounded-[10px] border border-line bg-surface px-2.5 text-[14px] text-ink focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
            />
          </label>
          {view.rangeInvalid ? (
            <span role="alert" className="text-[13px] text-action-now-fg">
              Start date is after the end date.
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
