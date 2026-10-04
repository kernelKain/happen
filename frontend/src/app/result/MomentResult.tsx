import { useId, useRef, useState } from "react";
import type { RecommendationResult } from "../../lib/api/recommendation";
import { hasConflict, safeSourceUrl } from "../../lib/evidenceView";
import { formatClock, labelFor } from "../../lib/labels";

const DIMENSIONS = ["conversation", "short_wait", "seating"] as const;

/** Render three timelines, the selected moment, the fallback, and accepted evidence. */
export function MomentResult({
  result,
  sample = false,
  onStartOver,
}: {
  result: RecommendationResult;
  sample?: boolean;
  onStartOver: () => void;
}) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const evidenceTitleId = useId();
  const selectedId = result.recommendation?.window_id;
  const provenance = result.provenance;
  const captured = new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(new Date(provenance.captured_at));

  function openEvidence() {
    setEvidenceOpen(true);
    queueMicrotask(() => closeRef.current?.focus());
  }

  function closeEvidence() {
    setEvidenceOpen(false);
    queueMicrotask(() => triggerRef.current?.focus());
  }

  return (
    <section className="matrix-frame result" aria-labelledby="matrix-heading">
      {sample ? (
        <p className="sample-banner" role="note">
          Layout sample. This shows how a finished result looks. Find the moment has not scored this
          visit.
        </p>
      ) : null}
      <div className="matrix-heading">
        <h2 id="matrix-heading">Tonight&apos;s moment</h2>
        <p className="technical">
          {labelFor(provenance.data_label)} · Captured {captured} · {provenance.timezone}
        </p>
      </div>
      <p className="technical">
        Scoring policy {provenance.scoring_policy_version}. Model {provenance.model_id}. Extraction
        schema {provenance.extraction_schema_version}.
      </p>
      {provenance.stale ? (
        <p className="notice-inline" role="status">
          This evidence is older than seven days.
        </p>
      ) : null}
      {result.warnings.map((warning) => (
        <p key={warning.code} className="disclaimer">
          {warning.message}
        </p>
      ))}

      {result.outcome === "partial_evidence" && result.recommendation ? (
        <p className="disclaimer" role="status">
          Partial result. Unknown intervals stay visible. They are not a recommendation.
        </p>
      ) : null}
      {provenance.data_label === "captured_fixture" ? (
        <p className="disclaimer" role="note">
          Captured fixture. This is saved place evidence, not a live search. Choose Start over to
          plan again.
        </p>
      ) : null}

      {result.outcome === "insufficient_evidence" || !result.recommendation ? (
        <div className="moment-card moment-empty">
          <h3>No moment selected</h3>
          <p>Fewer than two restaurants have enough comparable evidence.</p>
          <p>Choose Start over to restore the verified demo preset.</p>
        </div>
      ) : (
        <div className="decision">
          <article className="moment-card" aria-labelledby="recommended-heading">
            <p className="eyebrow" id="recommended-heading">
              Recommended
            </p>
            <h3>{result.recommendation.restaurant_name}</h3>
            <p className="technical arrival">
              {formatClock(result.recommendation.arrival_start)}–
              {formatClock(result.recommendation.arrival_end)}
            </p>
            <p className="label-pair">
              <span>Fit {labelFor(result.recommendation.fit_label)}</span>
              <span>Confidence {labelFor(result.recommendation.confidence_label)}</span>
            </p>
            <p>{result.recommendation.explanation}</p>
          </article>
          {result.fallback ? (
            <article className="fallback-card" aria-labelledby="fallback-heading">
              <p className="eyebrow" id="fallback-heading">
                Fallback
              </p>
              <h3>{result.fallback.restaurant_name}</h3>
              <p className="technical arrival">
                {formatClock(result.fallback.arrival_start)}–
                {formatClock(result.fallback.arrival_end)}
              </p>
              <p className="label-pair">
                <span>Fit {labelFor(result.fallback.fit_label)}</span>
                <span>Confidence {labelFor(result.fallback.confidence_label)}</span>
              </p>
              <p>{result.fallback.explanation}</p>
            </article>
          ) : null}
        </div>
      )}

      <ul className="legend">
        <li>
          <span className="swatch swatch-strong" aria-hidden="true" />
          Strong — supported
        </li>
        <li>
          <span className="swatch swatch-possible" aria-hidden="true" />
          Possible — partial support
        </li>
        <li>
          <span className="swatch swatch-weak" aria-hidden="true" />
          Weak — unfavorable
        </li>
        <li>
          <span className="swatch swatch-unknown" aria-hidden="true" />
          Unknown — not enough evidence
        </li>
      </ul>

      <div className="timelines">
        {result.candidates.map((candidate) => (
          <article key={candidate.candidate_id} className="timeline" aria-label={candidate.name}>
            <h3>{candidate.name}</h3>
            <ol>
              {candidate.windows.map((window) => {
                const selected = window.window_id === selectedId;
                return (
                  <li key={window.window_id}>
                    <button
                      type="button"
                      className={`band band-${window.fit_label}${selected ? " band-selected" : ""}`}
                      aria-current={selected ? "true" : undefined}
                    >
                      <span className="technical">
                        {formatClock(window.arrival_start)}–{formatClock(window.arrival_end)}
                      </span>
                      <span>Fit {labelFor(window.fit_label)}</span>
                      <span>Confidence {labelFor(window.confidence_label)}</span>
                      {selected ? <span className="selected-mark">Selected</span> : null}
                    </button>
                  </li>
                );
              })}
            </ol>
          </article>
        ))}
      </div>

      <div className="actions">
        <button type="button" ref={triggerRef} onClick={openEvidence}>
          Why this moment?
        </button>
        <button type="button" onClick={onStartOver}>
          Start over
        </button>
      </div>

      {evidenceOpen ? (
        <section
          className="evidence-panel"
          aria-labelledby={evidenceTitleId}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              closeEvidence();
            }
          }}
        >
          <div className="matrix-heading">
            <h3 id={evidenceTitleId}>Why this moment?</h3>
            <button type="button" ref={closeRef} onClick={closeEvidence}>
              Close evidence
            </button>
          </div>
          <div className="evidence-group">
            <h4>How this was chosen</h4>
            <p>
              Gemma extracts review quotes. Python scoring chooses the moment. The model does not
              pick the restaurant.
            </p>
            <p className="technical">
              Model {provenance.model_id}. Adapter {provenance.adapter_id}. Scoring policy{" "}
              {provenance.scoring_policy_version}. Extraction schema{" "}
              {provenance.extraction_schema_version}.
            </p>
            <p>Planning evidence—not live occupancy.</p>
          </div>
          <p className="technical">
            Rejected signals: {result.rejected_evidence_count}.{" "}
            {result.rejected_evidence_count === 0
              ? "No extracted quote was rejected."
              : "Rejected quotes are not shown and do not affect the score."}
          </p>
          {DIMENSIONS.map((dimension) => {
            const items = result.evidence.filter((item) => item.dimension === dimension);
            return (
              <div key={dimension} className="evidence-group">
                <h4>{labelFor(dimension)}</h4>
                {items.length === 0 ? (
                  <p>No accepted evidence for this priority.</p>
                ) : (
                  <>
                    {hasConflict(items.map((item) => item.polarity)) ? (
                      <p>This priority has conflicting evidence. Both quotes stay visible.</p>
                    ) : null}
                    {items.map((item) => {
                      const source = safeSourceUrl(item.source_url);
                      return (
                        <article key={item.evidence_id}>
                          <blockquote>{item.quoted_span}</blockquote>
                          <p className="technical">
                            {labelFor(item.polarity)} · {labelFor(item.temporal_hint)} · Confidence{" "}
                            {labelFor(item.extraction_confidence)}
                            {item.validation_status === "partially_accepted"
                              ? " · Partially accepted"
                              : ""}
                          </p>
                          {source ? (
                            <p>
                              <a href={source} target="_blank" rel="noopener noreferrer">
                                Open source
                              </a>
                            </p>
                          ) : (
                            <p>
                              The source link was omitted because it is not a normal web address.
                            </p>
                          )}
                        </article>
                      );
                    })}
                  </>
                )}
              </div>
            );
          })}
        </section>
      ) : null}
    </section>
  );
}
