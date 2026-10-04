import { useId, useState } from "react";
import type { EveningPlan, PlanStop, RefinementProposal } from "../../lib/api/plan";
import {
  arrivalCopy,
  busynessStatus,
  confidenceCopy,
  constraintCopy,
  evidenceShape,
  hoursCopy,
  outcomeLead,
  priceStatus,
  ratingStatus,
  retrievalCopy,
  visibleWarning,
} from "./flow";

const SOURCE_LABEL = {
  official: "Official site",
  maps: "Maps",
  community: "Community",
} as const;

const FIELD_LABEL: Record<string, string> = {
  destination: "Destination",
  date: "Date",
  time: "Time",
  intent: "Intent order",
  preferences: "Preferences",
  "party size": "Party size",
  budget: "Budget",
  accessibility: "Accessibility",
};

type TimelineProps = {
  plan: EveningPlan;
  timezone: string | null;
  intentCount: number;
};

/** A vertical evening of at most two stops. Evidence stays behind a disclosure. */
export function EveningTimeline({ plan, timezone, intentCount }: TimelineProps) {
  const stops = plan.stops.slice(0, 2);
  const shape = evidenceShape(plan, intentCount);
  const lead = outcomeLead(plan.outcome, stops.length);
  const notes = plan.warnings.filter((note) => visibleWarning(note) && note !== lead);
  return (
    <section className="plan" aria-labelledby="plan-heading">
      <h2 id="plan-heading">This evening</h2>
      <p>
        {timezone ? `Times use ${timezone}.` : "Times use the destination's local clock."}{" "}
        {`The evening starts at ${plan.local_start.slice(0, 5)} on ${plan.local_date}.`}
        {plan.party_size ? ` Party size ${plan.party_size}.` : ""}
      </p>
      {shape === "partial" ? <p>The evidence for this evening is incomplete.</p> : null}
      {lead ? <p>{lead}</p> : null}
      {stops.length > 0 ? (
        <ol className="timeline">
          {stops.map((stop) => (
            <StopCard key={stop.position} stop={stop} plan={plan} timezone={timezone} />
          ))}
        </ol>
      ) : null}
      {plan.transition ? (
        <p>
          Travel time is not verified.{" "}
          <a href={plan.transition.directions_url}>Directions between stops</a>
        </p>
      ) : null}
      {notes.map((note) => (
        <p key={note}>{note}</p>
      ))}
    </section>
  );
}

function StopCard({
  stop,
  plan,
  timezone,
}: {
  stop: PlanStop;
  plan: EveningPlan;
  timezone: string | null;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const groups = {
    official: stop.evidence.filter((item) => item.source === "official"),
    maps: stop.evidence.filter((item) => item.source === "maps"),
    community: stop.evidence.filter((item) => item.source === "community"),
  };
  const unknown = stop.unknown_fields.filter((field) => field !== "rating");
  return (
    <li>
      <h3>{`${stop.position}. ${stop.name}`}</h3>
      <p>{stop.explanation}</p>
      <p>{arrivalCopy(stop.position, plan.local_start, timezone)}</p>
      <p>{hoursCopy(stop)}</p>
      <p>{priceStatus(stop)}</p>
      <p>{busynessStatus(stop)}</p>
      <p>{ratingStatus(stop)}</p>
      <p>{confidenceCopy(stop.confidence)}</p>
      <p>{retrievalCopy(plan.retrieved_at)}</p>
      {stop.constraints.map((item) => {
        const line = constraintCopy(item);
        return line ? <p key={item.constraint}>{line}</p> : null;
      })}
      {unknown.length > 0 ? <p>{`Unknown: ${unknown.join(", ")}.`}</p> : null}
      {stop.website || stop.maps_link ? (
        <p className="stop-actions">
          {stop.website ? <a href={stop.website}>Official site</a> : null}
          {stop.maps_link ? <a href={stop.maps_link}>Directions</a> : null}
        </p>
      ) : null}
      {stop.warnings.filter(visibleWarning).map((note) => (
        <p key={note}>{note}</p>
      ))}
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? "Hide evidence" : "Show evidence"}
      </button>
      {open ? (
        <div id={panelId} className="evidence">
          {stop.components.length > 0 ? (
            <section>
              <h4>Checks</h4>
              <ul>
                {stop.components.map((item) => (
                  <li key={item.name}>{item.detail}</li>
                ))}
              </ul>
            </section>
          ) : null}
          <EvidenceGroup
            title={SOURCE_LABEL.official}
            items={groups.official}
            note="From the official site."
          />
          <EvidenceGroup title={SOURCE_LABEL.maps} items={groups.maps} note="From Maps." />
          <EvidenceGroup
            title={SOURCE_LABEL.community}
            items={groups.community}
            note="Community statements are not live facts."
          />
        </div>
      ) : null}
    </li>
  );
}

function EvidenceGroup({
  title,
  items,
  note,
}: {
  title: string;
  items: PlanStop["evidence"];
  note: string;
}) {
  return (
    <section className={`evidence-${title.toLowerCase().split(" ")[0]}`}>
      <h4>{title}</h4>
      <p>{note}</p>
      {items.length === 0 ? <p>None retrieved.</p> : null}
      {items.length > 0 ? (
        <ul>
          {items.map((item) => (
            <li key={`${item.source}-${item.retrieved_at}-${item.text}`}>
              <p>{item.text}</p>
              <p>{retrievalCopy(item.retrieved_at)}</p>
              {item.url ? <a href={item.url}>Source</a> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
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
  const empty =
    proposal.diff.added.length === 0 &&
    proposal.diff.removed.length === 0 &&
    proposal.diff.changed.length === 0;
  const blocked = proposal.follow_up !== null;
  return (
    <section className="diff" aria-labelledby="diff-heading">
      <h2 id="diff-heading">Review the change</h2>
      <p>{proposal.message}</p>
      {empty ? <p>Nothing in the evening would change.</p> : null}
      {proposal.diff.added.length > 0 ? (
        <div>
          <h3>Added</h3>
          <ul>
            {proposal.diff.added.map((field) => (
              <li key={field}>{FIELD_LABEL[field] ?? field}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {proposal.diff.removed.length > 0 ? (
        <div>
          <h3>Removed</h3>
          <ul>
            {proposal.diff.removed.map((field) => (
              <li key={field}>{FIELD_LABEL[field] ?? field}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {proposal.diff.changed.length > 0 ? (
        <div>
          <h3>Changed</h3>
          <ul>
            {proposal.diff.changed.map((change) => (
              <li key={change.field}>
                {`${FIELD_LABEL[change.field] ?? change.field}: ${change.before ?? "none"} to ${change.after ?? "none"}`}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {proposal.follow_up?.kind === "missing" ? <p>{proposal.follow_up.question}</p> : null}
      {proposal.follow_up?.kind === "ambiguity" ? <p>{proposal.follow_up.message}</p> : null}
      <div className="status-row">
        <button type="button" onClick={onApply} disabled={busy || blocked}>
          Apply
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </section>
  );
}
