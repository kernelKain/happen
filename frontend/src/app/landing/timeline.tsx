import { useEffect, useRef } from "react";
import type {
  EveningPlan,
  PlanningBrief,
  PlanStop,
  RefinementProposal,
  ResolvedDestination,
} from "../../lib/api/plan";
import { safeSourceUrl } from "../../lib/evidenceView";
import {
  checksView,
  couldNotConfirm,
  diffRows,
  formatInstant,
  hoursView,
  listAnd,
  MATCH_LABEL,
  outcomeCopy,
  planHeading,
  planNotes,
  planState,
  planSubline,
  SOURCE_KIND,
  SUPPORTS_LABEL,
  sourceGroups,
  stopView,
  unknownFieldLabel,
  VERIFICATION_LABEL,
} from "./present";

type TimelineProps = {
  plan: EveningPlan;
  brief: PlanningBrief | null;
  destination: ResolvedDestination | null;
  intentCount: number;
  sourcesId: string;
  selectedStop: number | null;
  onViewSources: (position: number) => void;
};

/** The evening as an itinerary of at most two stops. Sources open beside it. */
export function EveningTimeline({
  plan,
  brief,
  destination,
  intentCount,
  sourcesId,
  selectedStop,
  onViewSources,
}: TimelineProps) {
  const stops = plan.stops.slice(0, 2);
  const state = planState(plan, intentCount);
  const lead = outcomeCopy(state);
  const notes = planNotes(plan);
  const timezone = destination?.timezone_name ?? null;
  return (
    <section className="plan" aria-labelledby="plan-heading">
      <header className="plan-head">
        <h2 id="plan-heading">{planHeading(plan, destination, brief)}</h2>
        <p className="plan-sub">{planSubline(plan)}</p>
        <p className="plan-meta">
          Listings retrieved{" "}
          <time dateTime={plan.retrieved_at}>{formatInstant(plan.retrieved_at, timezone)}</time>
          {timezone ? "." : " (UTC)."}
        </p>
      </header>
      {lead ? (
        <p className={`plan-outcome plan-outcome-${state}`} data-state={state}>
          {lead}
        </p>
      ) : null}
      {stops.length > 0 ? (
        <ol className="timeline">
          {stops.map((stop, index) => (
            <StopCard
              key={stop.position}
              stop={stop}
              plan={plan}
              brief={brief}
              transitionUrl={index === 1 ? (plan.transition?.directions_url ?? null) : null}
              sourcesId={sourcesId}
              open={selectedStop === stop.position}
              onViewSources={() => onViewSources(stop.position)}
            />
          ))}
        </ol>
      ) : null}
      {notes.length > 0 ? (
        <ul className="plan-notes" aria-label="Notes about this plan">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function StopCard({
  stop,
  plan,
  brief,
  transitionUrl,
  sourcesId,
  open,
  onViewSources,
}: {
  stop: PlanStop;
  plan: EveningPlan;
  brief: PlanningBrief | null;
  transitionUrl: string | null;
  sourcesId: string;
  open: boolean;
  onViewSources: () => void;
}) {
  const view = stopView(stop, plan, brief);
  const website = stop.website ? safeSourceUrl(stop.website) : null;
  const directions = stop.maps_link ? safeSourceUrl(stop.maps_link) : null;
  const between = transitionUrl ? safeSourceUrl(transitionUrl) : null;
  const headingId = `stop-${stop.position}-name`;
  return (
    <li className="stop" aria-labelledby={headingId} data-selected={open}>
      <p className="stop-when">
        <span className="stop-seq" aria-hidden="true">
          {stop.position}
        </span>
        {view.when.datetime ? (
          <time dateTime={view.when.datetime}>{view.when.label}</time>
        ) : (
          <span>{view.when.label}</span>
        )}
        <span aria-hidden="true"> · </span>
        <span>{view.activity}</span>
      </p>
      <h3 id={headingId}>{stop.name}</h3>
      {stop.address ? <p className="stop-address">{stop.address}</p> : null}
      <p className="stop-timing" data-tone={view.timing.tone}>
        {view.timing.text}
      </p>
      {stop.position > 1 ? (
        <p className="stop-leg">
          Exact arrival is not calculated because travel time is unavailable.
          {between ? (
            <>
              {" "}
              <a href={between}>Open directions between stops</a>
            </>
          ) : null}
        </p>
      ) : null}
      {view.reasons.length > 0 ? (
        <div className="stop-why">
          <h4>Why it fits</h4>
          <ul>
            {view.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {view.facts.length > 0 ? (
        <p className="stop-facts">
          <span className="stop-label">Listing details:</span> {view.facts.join(" · ")}
        </p>
      ) : null}
      {view.contradicted.length > 0 ? (
        <p className="stop-against">
          <span className="stop-label">Listings suggest otherwise for:</span>{" "}
          {`${listAnd(view.contradicted)}.`}
        </p>
      ) : null}
      {view.unconfirmed.length > 0 ? (
        <p className="stop-unknown">
          <span className="stop-label">Couldn't confirm:</span> {couldNotConfirm(view.unconfirmed)}
        </p>
      ) : null}
      <p className="stop-actions">
        {website ? <a href={website}>Official site</a> : null}
        {directions ? <a href={directions}>Directions</a> : null}
        <button
          type="button"
          className="link-button"
          aria-expanded={open}
          aria-controls={sourcesId}
          onClick={onViewSources}
        >
          View sources
          <span className="visually-hidden">{` for ${stop.name}`}</span>
        </button>
      </p>
    </li>
  );
}

type SourcesProps = {
  id: string;
  stop: PlanStop;
  plan: EveningPlan;
  brief: PlanningBrief | null;
  timezone: string | null;
  onClose: () => void;
};

/** Why to trust a stop: what was checked, where it came from, and what is unknown. */
export function SourcesPanel({ id, stop, plan, brief, timezone, onClose }: SourcesProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const hours = hoursView(stop, plan.local_date);
  const groups = sourceGroups(stop, hours.today !== null);
  const checks = checksView(stop, plan, brief);
  const view = stopView(stop, plan, brief);
  const missingKinds = (["maps", "official", "community"] as const).filter(
    (kind) => !groups.some((group) => group.kind === kind),
  );

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <aside id={id} className="sources" aria-labelledby={`${id}-heading`}>
      <div className="sources-head">
        <h2 id={`${id}-heading`} tabIndex={-1} ref={headingRef}>
          Sources for {stop.name}
        </h2>
        <button type="button" className="link-button" onClick={onClose}>
          Close sources
        </button>
      </div>
      <p className="sources-note">
        Place information was retrieved through SerpApi. SerpApi delivers the listings below; the
        facts come from the sources named.
      </p>
      <section aria-labelledby={`${id}-checked`}>
        <h3 id={`${id}-checked`}>What was checked</h3>
        <dl className="checks">
          {checks.map((row) => (
            <div key={row.label}>
              <dt>{row.label}</dt>
              <dd>{row.result}</dd>
            </div>
          ))}
        </dl>
      </section>
      {hours.today || hours.week.length > 0 ? (
        <section aria-labelledby={`${id}-hours`}>
          <h3 id={`${id}-hours`}>Opening hours</h3>
          {hours.today ? (
            <p className="hours-today">
              <span className="stop-label">{`${hours.day}, your planned day:`}</span>{" "}
              {hours.today.includes(":")
                ? hours.today.split(":").slice(1).join(":").trim()
                : hours.today}
            </p>
          ) : (
            <p>{`Hours for ${hours.day} were not listed.`}</p>
          )}
          {hours.week.length > 0 ? (
            <details>
              <summary>Full weekly hours</summary>
              <ul className="hours-week">
                {hours.week.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </section>
      ) : null}
      <section aria-labelledby={`${id}-sources`}>
        <h3 id={`${id}-sources`}>Sources</h3>
        {groups.length === 0 ? <p>No source statements were retrieved for this stop.</p> : null}
        {groups.map((group) => (
          <div key={group.kind} className={`source-group evidence-${group.kind}`}>
            <h4>{group.title}</h4>
            <p className="source-note">{group.note}</p>
            {group.items.length > 0 ? (
              <ul>
                {group.items.map((item) => (
                  <li
                    key={item.text}
                    className={`evidence-item evidence-item-${group.kind}`}
                    data-verification={item.verification}
                  >
                    {item.text}
                    {item.verification !== "verified" ? (
                      <span className="verification">{` · ${VERIFICATION_LABEL[item.verification]}`}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
            {group.links.map((url, index) => (
              <a key={url} href={url} className="source-link">
                {group.links.length > 1 ? `${group.link} (${index + 1})` : group.link}
              </a>
            ))}
          </div>
        ))}
      </section>
      <section aria-labelledby={`${id}-unknown`}>
        <h3 id={`${id}-unknown`}>What remains unknown</h3>
        {view.unconfirmed.length > 0 || stop.hours_status !== "open" ? (
          <ul>
            {stop.hours_status !== "open" ? <li>{view.timing.text}.</li> : null}
            {view.unconfirmed.map((item) => (
              <li
                key={item}
              >{`${item.charAt(0).toUpperCase()}${item.slice(1)}: not confirmed by the retrieved listings.`}</li>
            ))}
          </ul>
        ) : (
          <p>Nothing you asked about is unconfirmed.</p>
        )}
        <p>
          Travel time, live crowd levels, reservations, and price conversion are never estimated.
        </p>
      </section>
      <details className="audit">
        <summary>Full audit</summary>
        <ul>
          {stop.evidence.map((item) => (
            <li key={`${item.source}-${item.field}-${item.text}`}>
              <p>{item.text}</p>
              <p className="audit-meta">
                {[
                  SOURCE_KIND[item.source].title,
                  SUPPORTS_LABEL[item.field] ?? "Supporting statement",
                  MATCH_LABEL[item.matched_by] ?? "",
                  VERIFICATION_LABEL[item.verification],
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <p className="audit-meta">
                Retrieved{" "}
                <time dateTime={item.retrieved_at}>
                  {formatInstant(item.retrieved_at, timezone)}
                </time>
                {item.url && safeSourceUrl(item.url) ? (
                  <>
                    {" · "}
                    <a href={safeSourceUrl(item.url) ?? undefined}>Source</a>
                  </>
                ) : null}
              </p>
            </li>
          ))}
        </ul>
        {missingKinds.length > 0 ? (
          <p>{`No statements retrieved from: ${missingKinds.map((kind) => SOURCE_KIND[kind].title.toLowerCase()).join(", ")}.`}</p>
        ) : null}
        {stop.unknown_fields.length > 0 ? (
          <p>{`Fields the listing left empty: ${stop.unknown_fields.map(unknownFieldLabel).join(", ")}.`}</p>
        ) : null}
      </details>
    </aside>
  );
}

type DiffProps = {
  proposal: RefinementProposal;
  busy: boolean;
  onApply: () => void;
  onCancel: () => void;
};

/** The current plan stays in place until Apply or Cancel. */
export function RefinementDiff({ proposal, busy, onApply, onCancel }: DiffProps) {
  const rows = diffRows(proposal);
  const blocked = proposal.follow_up !== null;
  return (
    <section className="diff" aria-labelledby="diff-heading">
      <h2 id="diff-heading">Review the change</h2>
      <p>Your current plan stays until you apply this.</p>
      {rows.length === 0 ? <p>Nothing in the evening would change.</p> : null}
      {rows.length > 0 ? (
        <ul className="diff-rows">
          {rows.map((row) => (
            <li key={`${row.kind}-${row.text}`} data-kind={row.kind}>
              <span className="diff-kind">{row.kind}</span> {row.text}
            </li>
          ))}
        </ul>
      ) : null}
      {proposal.follow_up?.kind === "missing" ? <p>{proposal.follow_up.question}</p> : null}
      {proposal.follow_up?.kind === "ambiguity" ? <p>{proposal.follow_up.message}</p> : null}
      <div className="status-row">
        <button type="button" onClick={onApply} disabled={busy || blocked}>
          Apply
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </section>
  );
}
