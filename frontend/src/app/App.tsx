import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import {
  type CanonicalPreset,
  contractMajor,
  LOCAL_PRESET,
  loadMetadata,
  type ServiceMeta,
  SUPPORTED_CONTRACT_MAJOR,
} from "../lib/api/meta";
import {
  RecommendationRequestError,
  type RecommendationResult,
  requestDemoRecommendation,
  requestLiveRecommendation,
} from "../lib/api/recommendation";
import { formatClock, labelFor, moveItem } from "../lib/labels";
import { errorTitle, fieldLabel } from "../lib/resultStates";
import { MomentResult } from "./result/MomentResult";

type ShellState =
  | { status: "loading" }
  | { status: "unavailable" }
  | { status: "mismatch"; meta: ServiceMeta }
  | { status: "ready"; meta: ServiceMeta };

type EvidenceSource = "live" | "fixture";

type JourneyState =
  | { status: "idle" }
  | { status: "gathering" }
  | { status: "result"; result: RecommendationResult }
  | {
      status: "error";
      code: string;
      message: string;
      nextAction: string;
      retryable: boolean;
      fields: { field: string; message: string }[];
      retryAfterSeconds: number | null;
      source: EvidenceSource;
      offerCaptured: boolean;
    };

const REPOSITORY_URL = "https://github.com/kernelKain/happen";

/** Render the planner and gate editing and submission on service metadata readiness. */
export function App() {
  const [reloadKey, setReloadKey] = useState(0);
  const [shell, setShell] = useState<ShellState>({ status: "loading" });
  const [draft, setDraft] = useState<CanonicalPreset>(LOCAL_PRESET);
  const [journey, setJourney] = useState<JourneyState>({ status: "idle" });
  const statusId = useId();
  // biome-ignore lint/correctness/useExhaustiveDependencies: reloadKey retries metadata
  useEffect(() => {
    let active = true;
    setShell({ status: "loading" });
    loadMetadata()
      .then((meta) => {
        if (!active) {
          return;
        }
        setDraft(meta.canonical_preset);
        if (contractMajor(meta.contract_version) !== SUPPORTED_CONTRACT_MAJOR) {
          setShell({ status: "mismatch", meta });
          return;
        }
        setShell({ status: "ready", meta });
      })
      .catch(() => {
        if (active) {
          setShell({ status: "unavailable" });
        }
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  const meta = shell.status === "ready" || shell.status === "mismatch" ? shell.meta : null;
  const preset = meta?.canonical_preset ?? LOCAL_PRESET;
  const choices = {
    neighborhoods: meta?.supported_neighborhoods ?? [preset.neighborhood],
    categories: meta?.supported_categories ?? [preset.restaurant_category],
    experiences: meta?.supported_experiences ?? [preset.desired_experience],
  };
  const timezone = meta?.timezone ?? "Asia/Kolkata";
  const gathering = journey.status === "gathering";
  const modelBlocked =
    shell.status === "ready" &&
    (shell.meta.model_status === "unavailable" || shell.meta.model_status === "loading");
  const canEdit = shell.status === "ready" && !gathering;
  const submitEnabled = canEdit && !modelBlocked;
  const inFlight = useRef(false);

  async function submitPlanner(source?: EvidenceSource) {
    if (shell.status !== "ready" || inFlight.current) {
      return;
    }
    const chosen: EvidenceSource = source ?? (shell.meta.live_available ? "live" : "fixture");
    inFlight.current = true;
    setJourney({ status: "gathering" });
    try {
      const result =
        chosen === "live"
          ? await requestLiveRecommendation(draft)
          : await requestDemoRecommendation(draft);
      setJourney({ status: "result", result });
    } catch (error) {
      const known = error instanceof RecommendationRequestError;
      const timedOut = error instanceof DOMException && error.name === "TimeoutError";
      setJourney({
        status: "error",
        code: known ? error.code : timedOut ? "PROCESSING_TIMEOUT" : "INTERNAL_ERROR",
        message: known
          ? error.message
          : timedOut
            ? "Gathering evidence took too long."
            : "Happen could not complete that request.",
        nextAction: known
          ? error.nextAction
          : timedOut
            ? "Try again. The next request is faster once the model is loaded."
            : "Try again in a moment.",
        retryable: known ? error.retryable : true,
        fields: known ? error.fields : [],
        retryAfterSeconds: known ? error.retryAfterSeconds : null,
        source: chosen,
        offerCaptured: known && chosen === "live" && error.fixtureAvailable,
      });
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <div className="shell">
      <header className="masthead">
        <div>
          <p className="eyebrow">Evening planning</p>
          <h1>Happen</h1>
          <p className="tagline">Know where. Know when.</p>
        </div>
        <div className="mode-block">
          <p className="badge">{modeLabel(shell)}</p>
          <p className="technical">
            {snapshotLine(shell)} · {timezone}
          </p>
        </div>
      </header>

      <section className="intro" aria-labelledby="thesis-heading">
        <h2 id="thesis-heading">Plan the evening</h2>
        <p className="thesis">
          Happen helps a friend choose not merely a restaurant, but the best-supported restaurant
          and arrival window for the experience they want.
        </p>
        <p className="preset-note">
          Demo preset: {labelFor(preset.neighborhood)} dinner, {formatRange(preset)}.
          {shell.status === "unavailable"
            ? " These choices are stored in the page because the service could not confirm them."
            : " Choices come from the Happen service."}
        </p>
      </section>

      <ShellNotice shell={shell} onRetry={() => setReloadKey((value) => value + 1)} />
      <ModelNotice shell={shell} onRetry={() => setReloadKey((value) => value + 1)} />

      <form
        className="planner"
        aria-busy={shell.status === "loading" || gathering}
        onSubmit={(event) => {
          event.preventDefault();
          void submitPlanner();
        }}
      >
        <div className="fields">
          <Field label="Neighbourhood" id="neighborhood">
            <select
              id="neighborhood"
              value={draft.neighborhood}
              disabled={!canEdit}
              onChange={(event) => setDraft({ ...draft, neighborhood: event.target.value })}
            >
              {choices.neighborhoods.map((value) => (
                <option key={value} value={value}>
                  {labelFor(value)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Category" id="category">
            <select
              id="category"
              value={draft.restaurant_category}
              disabled={!canEdit}
              onChange={(event) => setDraft({ ...draft, restaurant_category: event.target.value })}
            >
              {choices.categories.map((value) => (
                <option key={value} value={value}>
                  {labelFor(value)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Arrival from" id="arrival-start">
            <input
              id="arrival-start"
              type="time"
              step={1800}
              value={draft.arrival_start}
              disabled={!canEdit}
              onChange={(event) => setDraft({ ...draft, arrival_start: event.target.value })}
            />
          </Field>
          <Field label="Arrival until" id="arrival-end">
            <input
              id="arrival-end"
              type="time"
              step={1800}
              value={draft.arrival_end}
              disabled={!canEdit}
              onChange={(event) => setDraft({ ...draft, arrival_end: event.target.value })}
            />
          </Field>
          <Field label="Desired experience" id="experience">
            <select
              id="experience"
              value={draft.desired_experience}
              disabled={!canEdit}
              onChange={(event) => setDraft({ ...draft, desired_experience: event.target.value })}
            >
              {choices.experiences.map((value) => (
                <option key={value} value={value}>
                  {labelFor(value)}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <fieldset className="priorities" disabled={!canEdit}>
          <legend>Priority order</legend>
          <ol>
            {draft.priorities.map((priority, index) => (
              <li key={priority}>
                <span className="rank">{index + 1}</span>
                <span>{labelFor(priority)}</span>
                <span className="rank-actions">
                  <button
                    type="button"
                    aria-label={`Move ${labelFor(priority)} earlier`}
                    onClick={() =>
                      setDraft({ ...draft, priorities: moveItem(draft.priorities, index, -1) })
                    }
                  >
                    Earlier
                  </button>
                  <button
                    type="button"
                    aria-label={`Move ${labelFor(priority)} later`}
                    onClick={() =>
                      setDraft({ ...draft, priorities: moveItem(draft.priorities, index, 1) })
                    }
                  >
                    Later
                  </button>
                </span>
              </li>
            ))}
          </ol>
        </fieldset>

        <p className="mode-copy">{evidenceCopy(shell)}</p>
        <p id={statusId} className="submit-reason" role={gathering ? "status" : undefined}>
          {gathering ? "Gathering evidence. Wait for this request to finish." : submitReason(shell)}
        </p>

        <div className="actions">
          <button type="submit" disabled={!submitEnabled} aria-describedby={statusId}>
            Find the moment
          </button>
          <button
            type="button"
            onClick={() => setDraft(preset)}
            disabled={shell.status === "loading"}
          >
            Restore demo preset
          </button>
        </div>
      </form>

      {journey.status === "error" ? (
        <div className="notice notice-error" role="alert">
          <p>{errorTitle(journey.code)}</p>
          <p>{journey.message}</p>
          <p>{journey.nextAction}</p>
          {journey.retryAfterSeconds !== null && journey.retryAfterSeconds > 0 ? (
            <p>Wait {journey.retryAfterSeconds} seconds before trying again.</p>
          ) : null}
          {journey.fields.length > 0 ? (
            <ul>
              {journey.fields.map((field) => (
                <li key={field.field}>
                  {fieldLabel(field.field)}: {field.message}
                </li>
              ))}
            </ul>
          ) : null}
          {journey.retryable ? (
            <button type="button" onClick={() => void submitPlanner(journey.source)}>
              Retry
            </button>
          ) : null}
          {journey.offerCaptured ? (
            <button type="button" onClick={() => void submitPlanner("fixture")}>
              Use captured evidence
            </button>
          ) : null}
        </div>
      ) : null}
      {journey.status === "result" ? (
        <MomentResult
          result={journey.result}
          onStartOver={() => {
            setJourney({ status: "idle" });
            setDraft(preset);
          }}
        />
      ) : null}
      {journey.status !== "result" ? (
        <section className="matrix-frame" aria-labelledby="matrix-heading">
          <div className="matrix-heading">
            <h2 id="matrix-heading">Tonight&apos;s moment</h2>
            <p>
              {gathering
                ? "Gathering evidence. Wait for this request to finish."
                : "Nothing has been recommended yet."}
            </p>
          </div>
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
          <p className="matrix-empty">
            Three restaurant timelines will appear here after evidence is gathered. Missing evidence
            stays Unknown.
          </p>
        </section>
      ) : null}

      <footer className="colophon">
        <p>Planning evidence—not live occupancy.</p>
        <p>
          Gemma extracts review evidence. Python scoring chooses the moment. SerpApi is the only
          place-data source.
        </p>
        <p>
          <a href={REPOSITORY_URL} rel="noopener noreferrer">
            Project repository
          </a>
        </p>
      </footer>
    </div>
  );
}

/** Render loading, retry, or refresh guidance for the current service state. */
function ShellNotice({ shell, onRetry }: { shell: ShellState; onRetry: () => void }) {
  if (shell.status === "loading") {
    return (
      <p className="notice" role="status">
        Checking the Happen service.
      </p>
    );
  }
  if (shell.status === "unavailable") {
    return (
      <div className="notice notice-error" role="alert">
        <p>The Happen service is unavailable.</p>
        <p>Retry the connection. The page will not invent a recommendation.</p>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }
  if (shell.status === "mismatch") {
    return (
      <div className="notice notice-error" role="alert">
        <p>A new version is available.</p>
        <p>Refresh the page so the planner matches the service. Submission stays off.</p>
        <button type="button" onClick={() => window.location.reload()}>
          Refresh the page
        </button>
      </div>
    );
  }
  return null;
}

/** Name a model dependency failure and give the next action. */
function ModelNotice({ shell, onRetry }: { shell: ShellState; onRetry: () => void }) {
  if (shell.status !== "ready") {
    return null;
  }
  if (shell.meta.model_status === "loading") {
    return (
      <div className="notice" role="status">
        <p>The evidence model is waking up.</p>
        <p>Wait, then choose Find the moment. Happen will not use another extractor.</p>
      </div>
    );
  }
  if (shell.meta.model_status === "unavailable") {
    return (
      <div className="notice notice-error" role="alert">
        <p>The evidence model is unavailable.</p>
        <p>
          Retry the connection after the model file is installed. No recommendation will be
          invented.
        </p>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }
  return null;
}

/** Wrap a form control in a label associated with its element ID. */
function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <label className="field" htmlFor={id}>
      <span>{label}</span>
      {children}
    </label>
  );
}

/** Describe service readiness and prefer live evidence when both sources are available. */
function modeLabel(shell: ShellState): string {
  if (shell.status === "loading") {
    return "Checking service";
  }
  if (shell.status === "unavailable") {
    return "Service unavailable";
  }
  if (shell.status === "mismatch") {
    return "Update required";
  }
  if (shell.meta.live_available) {
    return "Live evidence";
  }
  if (shell.meta.fixture_available) {
    return "Captured fixture";
  }
  return "Synthetic fixture";
}

/** Explain which evidence sources the ready service reports as available. */
function evidenceCopy(shell: ShellState): string {
  if (shell.status !== "ready") {
    return "Live and captured evidence can be used only after the service responds.";
  }
  if (shell.meta.live_available && shell.meta.fixture_available) {
    return "Live evidence is available. Captured evidence stays a separate, labeled path.";
  }
  if (shell.meta.live_available) {
    return "Live evidence is available. Captured evidence is not installed.";
  }
  if (shell.meta.fixture_available) {
    return "Captured evidence is available and will be labeled as a captured fixture.";
  }
  return "Find the moment scores the labeled synthetic fixture. It is not a SerpApi capture.";
}

/** Explain when Find the moment can score the synthetic fixture. */
function submitReason(shell: ShellState): string {
  if (shell.status === "loading") {
    return "Find the moment stays off until the service responds.";
  }
  if (shell.status === "unavailable") {
    return "Find the moment stays off because the service is unavailable.";
  }
  if (shell.status === "mismatch") {
    return "Find the moment stays off until this page matches the service.";
  }
  if (shell.meta.model_status === "loading") {
    return "The evidence model is still loading, so Find the moment stays off.";
  }
  if (shell.meta.model_status === "unavailable") {
    return "The evidence model is unavailable, so Find the moment stays off.";
  }
  if (shell.meta.live_available) {
    return (
      "Find the moment asks SerpApi for current place evidence. " +
      "It does not run until you choose it."
    );
  }
  if (shell.meta.fixture_available) {
    return (
      "Find the moment scores the captured Indiranagar fixture. " +
      "It does not run until you choose it."
    );
  }
  return "Find the moment scores the synthetic fixture. It does not run until you choose it.";
}

/** Name the evidence snapshot the ready service can use. */
function snapshotLine(shell: ShellState): string {
  if (shell.status !== "ready") {
    return "No snapshot yet";
  }
  if (shell.meta.live_available && shell.meta.fixture_available) {
    return "Live evidence, with a captured snapshot";
  }
  if (shell.meta.live_available) {
    return "Live evidence";
  }
  if (shell.meta.fixture_available) {
    return "Captured snapshot installed";
  }
  return "No snapshot yet";
}

/** Format the preset arrival window as two display times separated by an en dash. */
function formatRange(preset: CanonicalPreset): string {
  return `${formatClock(preset.arrival_start)}–${formatClock(preset.arrival_end)}`;
}
