import { useEffect, useId, useRef, useState } from "react";
import type { EveningPlan, FollowUp, PlanningBrief, ResolvedDestination } from "../../lib/api/plan";
import {
  interpretBrief,
  type PlanFetch,
  PlanRequestError,
  refineBrief,
  requestPlan,
  resolveDestination,
} from "../../lib/api/planClient";
import { EXAMPLE_EVENINGS } from "./examples";
import {
  activeFollowUp,
  applyLocalTime,
  budgetIssue,
  canFindPlan,
  clockForInput,
  moveIntent,
  outcomeLead,
  partySizeIssue,
  preferenceIssue,
  preferenceList,
  restorePrompt,
  shouldResolve,
  visibleWarning,
} from "./flow";
import { Mark } from "./Mark";
import "./landing.css";

type LandingProps = {
  initialEvening?: string;
  fetchImpl?: PlanFetch;
};

type Busy = "reading" | "checking" | "finding";

type Failure = {
  message: string;
  next: string;
  retry: "interpret" | "resolve" | "plan" | null;
};

const BUSY_LABEL: Record<Busy, string> = {
  reading: "Reading the evening.",
  checking: "Checking the destination.",
  finding: "Finding live places.",
};

const SOURCE_LABEL = {
  official: "Official",
  maps: "Maps",
  community: "Community",
} as const;

/** Customer landing. Place search starts only after Find the plan. */
export function Landing({ initialEvening = "", fetchImpl }: LandingProps) {
  const errorId = useId();
  const partyErrorId = useId();
  const budgetErrorId = useId();
  const preferenceErrorId = useId();
  const dateHintId = useId();
  const findNoteId = useId();
  const alertRef = useRef<HTMLDivElement>(null);
  const followRef = useRef<HTMLInputElement>(null);
  const choiceRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const requestLock = useRef(false);

  const [evening, setEvening] = useState(initialEvening);
  const [originalPrompt, setOriginalPrompt] = useState<string | null>(null);
  const [brief, setBrief] = useState<PlanningBrief | null>(null);
  const [followUp, setFollowUp] = useState<FollowUp | null>(null);
  const [destination, setDestination] = useState<ResolvedDestination | null>(null);
  const [choices, setChoices] = useState<ResolvedDestination[]>([]);
  const [billed, setBilled] = useState(0);
  const [busy, setBusy] = useState<Busy | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [plan, setPlan] = useState<EveningPlan | null>(null);
  const [partyDraft, setPartyDraft] = useState("");
  const [budgetAmount, setBudgetAmount] = useState("");
  const [budgetCurrency, setBudgetCurrency] = useState("");
  const [preferenceDraft, setPreferenceDraft] = useState("");
  const [answerDraft, setAnswerDraft] = useState("");
  const [selectedChoice, setSelectedChoice] = useState<string | null>(null);

  const choosing = choices.length > 0;
  const shownFollowUp = brief ? activeFollowUp(brief, followUp, choosing) : null;
  const question =
    shownFollowUp?.kind === "missing"
      ? shownFollowUp.question
      : shownFollowUp?.kind === "ambiguity"
        ? shownFollowUp.message
        : "";
  const partyMessage = partySizeIssue(partyDraft);
  const budgetMessage = budgetIssue(budgetAmount, budgetCurrency);
  const preferenceMessage = preferenceIssue(preferenceDraft);
  const ready = canFindPlan({
    destination,
    brief,
    followUp: shownFollowUp,
    choosing,
    busy: busy !== null,
  });
  const showFind = ready && failure === null;
  const showCheck = Boolean(
    brief?.destination_text?.trim() &&
      !destination?.timezone_name &&
      !choosing &&
      busy === null &&
      failure?.retry !== "resolve" &&
      !(shownFollowUp?.kind === "missing" && shownFollowUp.field === "destination"),
  );

  useEffect(() => {
    if (failure) {
      alertRef.current?.focus();
    }
  }, [failure]);

  useEffect(() => {
    setAnswerDraft("");
    if (question) {
      followRef.current?.focus();
    }
  }, [question]);

  useEffect(() => {
    if (choices.length > 0) {
      choiceRef.current?.focus();
    }
  }, [choices]);

  function begin(): number | null {
    if (requestLock.current) {
      return null;
    }
    requestLock.current = true;
    const id = generation.current + 1;
    generation.current = id;
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    return id;
  }

  function end(id: number) {
    if (id === generation.current) {
      requestLock.current = false;
    }
  }

  function cancel() {
    generation.current += 1;
    requestLock.current = false;
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(null);
  }

  function rememberBrief(next: PlanningBrief) {
    setBrief(next);
    setPartyDraft(next.party_size === null ? "" : String(next.party_size));
    setBudgetAmount(next.budget?.amount ?? "");
    setBudgetCurrency(next.budget?.currency ?? "");
    setPreferenceDraft(next.preferences.join(", "));
  }

  function clearAsked(field: FollowUp["field"]) {
    setFollowUp((current) => {
      if (!current) {
        return current;
      }
      if (current.kind === "missing" && current.field === field) {
        return null;
      }
      if (current.kind === "ambiguity" && current.field === field) {
        return null;
      }
      return current;
    });
  }

  function settle(error: unknown, retry: Failure["retry"]): Failure | null {
    if (error instanceof DOMException && error.name === "AbortError") {
      return null;
    }
    if (error instanceof PlanRequestError) {
      return {
        message: error.message,
        next: error.nextAction,
        retry: error.retryable ? retry : null,
      };
    }
    return {
      message: "Happen could not be reached.",
      next: "Try again.",
      retry,
    };
  }

  async function resolveInto(current: PlanningBrief, id: number) {
    const query = current.destination_text?.trim();
    if (!query || id !== generation.current) {
      return;
    }
    const phrase = current.pending_date?.phrase;
    const resolution = await resolveDestination(
      {
        query,
        pending_date: phrase === "today" || phrase === "tomorrow" ? phrase : undefined,
        local_date: current.local_date,
        local_start: current.local_start,
      },
      { signal: abortRef.current?.signal, fetchImpl },
    );
    if (id !== generation.current) {
      return;
    }
    setBilled((spent) => spent + resolution.billed_requests);
    if (resolution.status === "ambiguous") {
      setDestination(null);
      setSelectedChoice(null);
      setChoices(resolution.choices);
      return;
    }
    if (resolution.status === "resolved" && resolution.destination?.timezone_name) {
      setChoices([]);
      setSelectedChoice(null);
      setDestination(resolution.destination);
      setBrief((existing) =>
        existing ? applyLocalTime(existing, resolution.local_time) : existing,
      );
      return;
    }
    setDestination(null);
    setChoices([]);
    if (resolution.status === "budget_exhausted") {
      setFailure({
        message: "The search allowance for this plan has been reached.",
        next: "Try again later.",
        retry: null,
      });
      return;
    }
    setFailure({
      message: "Happen could not place that destination in a local time.",
      next: "Choose a different place.",
      retry: null,
    });
  }

  async function interpretPrompt(prompt: string) {
    const id = begin();
    if (id === null) {
      return;
    }
    setComposerError(null);
    setFailure(null);
    setBusy("reading");
    try {
      const result = await interpretBrief(prompt, {
        signal: abortRef.current?.signal,
        fetchImpl,
      });
      if (id !== generation.current) {
        return;
      }
      const next = restorePrompt(result.brief, prompt);
      setOriginalPrompt(prompt);
      rememberBrief(next);
      setFollowUp(result.follow_up);
      setDestination(null);
      setChoices([]);
      setSelectedChoice(null);
      setBilled(0);
      setPlan(null);
      if (shouldResolve(next, result.follow_up)) {
        setBusy("checking");
        await resolveInto(next, id);
      }
    } catch (error) {
      if (id !== generation.current) {
        return;
      }
      const nextFailure = settle(error, "interpret");
      if (nextFailure) {
        setFailure(nextFailure);
      }
    } finally {
      if (id === generation.current) {
        setBusy(null);
      }
      end(id);
    }
  }

  async function checkPlace() {
    if (!brief) {
      return;
    }
    const id = begin();
    if (id === null) {
      return;
    }
    setFailure(null);
    setBusy("checking");
    try {
      await resolveInto(brief, id);
    } catch (error) {
      if (id !== generation.current) {
        return;
      }
      const nextFailure = settle(error, "resolve");
      if (nextFailure) {
        setFailure(nextFailure);
      }
    } finally {
      if (id === generation.current) {
        setBusy(null);
      }
      end(id);
    }
  }

  async function answer(revision: string) {
    if (!brief || !originalPrompt) {
      return;
    }
    const cleaned = revision.trim();
    if (!cleaned) {
      return;
    }
    const id = begin();
    if (id === null) {
      return;
    }
    setBusy("reading");
    setFailure(null);
    try {
      const proposal = await refineBrief(restorePrompt(brief, originalPrompt), cleaned, {
        signal: abortRef.current?.signal,
        fetchImpl,
      });
      if (id !== generation.current) {
        return;
      }
      const next = restorePrompt(proposal.proposed, originalPrompt);
      const changed = next.destination_text !== brief.destination_text;
      rememberBrief(next);
      setFollowUp(proposal.follow_up);
      setPlan(null);
      if (changed) {
        setDestination(null);
        setChoices([]);
        setSelectedChoice(null);
      }
      if ((changed || !destination) && shouldResolve(next, proposal.follow_up)) {
        setBusy("checking");
        await resolveInto(next, id);
      }
    } catch (error) {
      if (id !== generation.current) {
        return;
      }
      const nextFailure = settle(error, "interpret");
      if (nextFailure) {
        setFailure(nextFailure);
      }
    } finally {
      if (id === generation.current) {
        setBusy(null);
      }
      end(id);
    }
  }

  async function confirmChoice(choice: ResolvedDestination) {
    if (!brief) {
      return;
    }
    const id = begin();
    if (id === null) {
      return;
    }
    setChoices([]);
    setSelectedChoice(null);
    setPlan(null);
    setFailure(null);
    if (!choice.timezone_name) {
      setDestination(null);
      setFailure({
        message: "Happen could not place that destination in a local time.",
        next: "Choose a different place.",
        retry: null,
      });
      end(id);
      return;
    }
    setDestination(choice);
    const phrase = brief.pending_date?.phrase;
    const needsDate = !brief.local_date && (phrase === "today" || phrase === "tomorrow");
    if (!needsDate) {
      end(id);
      return;
    }
    setBusy("checking");
    try {
      await resolveInto({ ...brief, destination_text: choice.label }, id);
    } catch (error) {
      if (id !== generation.current) {
        return;
      }
      const nextFailure = settle(error, "resolve");
      if (nextFailure) {
        setFailure(nextFailure);
      }
    } finally {
      if (id === generation.current) {
        setBusy(null);
      }
      end(id);
    }
  }

  async function findPlan() {
    if (!brief || !destination?.timezone_name || !brief.local_date || !brief.local_start) {
      return;
    }
    if (billed >= 8) {
      setFailure({
        message: "The search allowance for this plan has been reached.",
        next: "Try again later.",
        retry: null,
      });
      return;
    }
    const id = begin();
    if (id === null) {
      return;
    }
    setFailure(null);
    setBusy("finding");
    setPlan(null);
    try {
      const eveningPlan = await requestPlan(
        {
          destination,
          intents: brief.intents,
          local_date: brief.local_date,
          local_start: brief.local_start,
          preferences: brief.preferences,
          prior_billed_requests: billed,
        },
        { signal: abortRef.current?.signal, fetchImpl },
      );
      if (id !== generation.current) {
        return;
      }
      setPlan(eveningPlan);
    } catch (error) {
      if (id !== generation.current) {
        return;
      }
      const nextFailure = settle(error, "plan");
      if (nextFailure) {
        setFailure(nextFailure);
      }
    } finally {
      if (id === generation.current) {
        setBusy(null);
      }
      end(id);
    }
  }

  function retry() {
    if (!failure?.retry || busy) {
      return;
    }
    if (failure.retry === "interpret") {
      const cleaned = evening.trim();
      if (cleaned) {
        void interpretPrompt(cleaned);
      }
      return;
    }
    if (failure.retry === "resolve") {
      void checkPlace();
      return;
    }
    void findPlan();
  }

  function submitComposer(value: string) {
    const cleaned = value.trim();
    if (!cleaned) {
      setComposerError("Describe the evening before Happen can plan it.");
      return;
    }
    void interpretPrompt(cleaned);
  }

  return (
    <div className="landing">
      <a className="skip" href="#evening">
        Skip to the evening
      </a>
      <header className="landing-bar">
        <p className="brand">
          <Mark />
          <span className="wordmark">Happen</span>
        </p>
      </header>
      <main>
        <section className="landing-hero" aria-labelledby="promise">
          <div className="promise">
            <h1 id="promise">One evening, held to two stops.</h1>
            <p>
              Describe the night in your own words. Happen plans that evening from live place
              evidence, and it stops at two.
            </p>
          </div>
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              submitComposer(evening);
            }}
          >
            <label htmlFor="evening">Describe the evening</label>
            <textarea
              id="evening"
              name="evening"
              rows={5}
              value={evening}
              disabled={busy !== null}
              aria-invalid={composerError !== null}
              aria-describedby={composerError ? errorId : undefined}
              placeholder="Dinner in Kyoto tomorrow at 7, then a short walk."
              onChange={(event) => {
                setEvening(event.target.value);
                if (composerError) {
                  setComposerError(null);
                }
              }}
            />
            {composerError ? (
              <p id={errorId} className="composer-error" role="alert">
                {composerError}
              </p>
            ) : null}
            <button type="submit" disabled={busy !== null}>
              Plan this evening
            </button>
          </form>
        </section>

        <section className="flow" aria-labelledby="flow-heading" aria-busy={busy !== null}>
          <h2 id="flow-heading" className="visually-hidden">
            Planning
          </h2>
          {busy ? (
            <div className="status-row">
              <p className="held" role="status">
                {BUSY_LABEL[busy]}
              </p>
              <button type="button" onClick={cancel}>
                Cancel
              </button>
            </div>
          ) : null}
          {failure ? (
            <div className="notice" role="alert" tabIndex={-1} ref={alertRef}>
              <p>{failure.message}</p>
              <p>{failure.next}</p>
              {failure.retry ? (
                <button type="button" onClick={retry} disabled={busy !== null}>
                  Try again
                </button>
              ) : null}
            </div>
          ) : null}
          {choosing ? (
            <form
              className="follow-up"
              onSubmit={(event) => {
                event.preventDefault();
                const choice = choices.find((item) => item.label === selectedChoice);
                if (choice) {
                  void confirmChoice(choice);
                }
              }}
            >
              <fieldset>
                <legend>Which place did you mean?</legend>
                {choices.map((choice, index) => (
                  <label key={choice.label}>
                    <input
                      ref={index === 0 ? choiceRef : undefined}
                      type="radio"
                      name="destination-choice"
                      value={choice.label}
                      checked={selectedChoice === choice.label}
                      onChange={() => setSelectedChoice(choice.label)}
                    />
                    {choice.label}
                  </label>
                ))}
              </fieldset>
              <button type="submit" disabled={!selectedChoice || busy !== null}>
                Use this place
              </button>
            </form>
          ) : null}
          {shownFollowUp && busy === null ? (
            <form
              className="follow-up"
              onSubmit={(event) => {
                event.preventDefault();
                if (shownFollowUp.kind === "ambiguity") {
                  const selected = new FormData(event.currentTarget).get("follow-up-choice");
                  if (typeof selected === "string") {
                    void answer(selected);
                  }
                  return;
                }
                void answer(answerDraft);
              }}
            >
              {shownFollowUp.kind === "ambiguity" ? (
                <fieldset>
                  <legend>{shownFollowUp.message}</legend>
                  {shownFollowUp.candidates.map((candidate, index) => (
                    <label key={candidate}>
                      <input
                        ref={index === 0 ? followRef : undefined}
                        type="radio"
                        name="follow-up-choice"
                        value={candidate}
                        required
                      />
                      {candidate}
                    </label>
                  ))}
                </fieldset>
              ) : (
                <>
                  <label htmlFor="follow-up">{shownFollowUp.question}</label>
                  <input
                    id="follow-up"
                    ref={followRef}
                    value={answerDraft}
                    onChange={(event) => setAnswerDraft(event.target.value)}
                  />
                </>
              )}
              <button
                type="submit"
                disabled={
                  busy !== null || (shownFollowUp.kind === "missing" && answerDraft.trim() === "")
                }
              >
                {shownFollowUp.kind === "ambiguity" ? "Use this answer" : "Answer"}
              </button>
            </form>
          ) : null}
          {brief && originalPrompt ? (
            <section className="brief" aria-labelledby="brief-heading">
              <h2 id="brief-heading">Your evening</h2>
              <p className="original">Your words: {originalPrompt}</p>
              {destination?.timezone_name ? (
                <p>
                  {destination.label}. Local time uses {destination.timezone_name}.
                </p>
              ) : null}
              <div className="brief-fields">
                <label className="brief-span">
                  Destination
                  <input
                    value={brief.destination_text ?? ""}
                    disabled={busy !== null}
                    onChange={(event) => {
                      const value = event.target.value;
                      setBrief({ ...brief, destination_text: value || null });
                      setDestination(null);
                      setChoices([]);
                      setSelectedChoice(null);
                      setPlan(null);
                      if (value.trim()) {
                        clearAsked("destination");
                      }
                    }}
                  />
                </label>
                <label>
                  Local date
                  <input
                    type="date"
                    value={brief.local_date ?? ""}
                    disabled={busy !== null}
                    aria-describedby={
                      brief.pending_date && !brief.local_date ? dateHintId : undefined
                    }
                    onChange={(event) => {
                      const value = event.target.value;
                      setBrief({
                        ...brief,
                        local_date: value || null,
                        pending_date: value ? null : brief.pending_date,
                      });
                      if (value) {
                        clearAsked("date");
                      }
                    }}
                  />
                </label>
                <label>
                  Local time
                  <input
                    type="time"
                    value={clockForInput(brief.local_start)}
                    disabled={busy !== null}
                    onChange={(event) => {
                      const value = event.target.value;
                      setBrief({ ...brief, local_start: value || null });
                      if (value) {
                        clearAsked("time");
                      }
                    }}
                  />
                </label>
                {brief.pending_date && !brief.local_date ? (
                  <p id={dateHintId} className="field-hint brief-span">
                    You said {brief.pending_date.phrase.replaceAll("_", " ")}.
                  </p>
                ) : null}
                <label>
                  Party size
                  <input
                    inputMode="numeric"
                    value={partyDraft}
                    disabled={busy !== null}
                    aria-invalid={partyMessage !== null}
                    aria-describedby={partyMessage ? partyErrorId : undefined}
                    onChange={(event) => {
                      const value = event.target.value;
                      setPartyDraft(value);
                      if (partySizeIssue(value)) {
                        return;
                      }
                      setBrief({
                        ...brief,
                        party_size: value.trim() ? Number(value) : null,
                      });
                    }}
                  />
                </label>
                <label>
                  Budget amount
                  <input
                    inputMode="decimal"
                    value={budgetAmount}
                    disabled={busy !== null}
                    aria-invalid={budgetMessage !== null}
                    aria-describedby={budgetMessage ? budgetErrorId : undefined}
                    onChange={(event) => {
                      const amount = event.target.value;
                      setBudgetAmount(amount);
                      if (budgetIssue(amount, budgetCurrency)) {
                        return;
                      }
                      setBrief({ ...brief, budget: budgetFrom(brief, amount, budgetCurrency) });
                    }}
                  />
                </label>
                <label>
                  Currency
                  <input
                    value={budgetCurrency}
                    disabled={busy !== null}
                    aria-invalid={budgetMessage !== null}
                    aria-describedby={budgetMessage ? budgetErrorId : undefined}
                    onChange={(event) => {
                      const currency = event.target.value;
                      setBudgetCurrency(currency);
                      if (budgetIssue(budgetAmount, currency)) {
                        return;
                      }
                      setBrief({ ...brief, budget: budgetFrom(brief, budgetAmount, currency) });
                    }}
                  />
                </label>
                <label className="brief-span">
                  Preferences
                  <input
                    value={preferenceDraft}
                    disabled={busy !== null}
                    aria-invalid={preferenceMessage !== null}
                    aria-describedby={preferenceMessage ? preferenceErrorId : undefined}
                    onChange={(event) => {
                      const value = event.target.value;
                      setPreferenceDraft(value);
                      if (preferenceIssue(value)) {
                        return;
                      }
                      setBrief({ ...brief, preferences: preferenceList(value) });
                    }}
                  />
                </label>
              </div>
              {partyMessage ? (
                <p id={partyErrorId} className="composer-error" role="alert">
                  {partyMessage}
                </p>
              ) : null}
              {budgetMessage ? (
                <p id={budgetErrorId} className="composer-error" role="alert">
                  {budgetMessage}
                </p>
              ) : null}
              {preferenceMessage ? (
                <p id={preferenceErrorId} className="composer-error" role="alert">
                  {preferenceMessage}
                </p>
              ) : null}
              {brief.budget?.tier ? <p>Price range: {brief.budget.tier}.</p> : null}
              <div className="intent-order">
                <h3>Intent order</h3>
                {brief.intents.length === 0 ? <p>No stop is listed yet.</p> : null}
                <ol>
                  {brief.intents.map((intent, index) => (
                    <li key={`${intent.kind}-${intent.label}`}>
                      <span>{`${intent.position}. ${intent.label}`}</span>
                      <button
                        type="button"
                        disabled={busy !== null || index === 0}
                        aria-label={`Move ${intent.label} earlier`}
                        onClick={() => {
                          setBrief({ ...brief, intents: moveIntent(brief.intents, index, -1) });
                          clearAsked("primary_intent");
                        }}
                      >
                        Earlier
                      </button>
                      <button
                        type="button"
                        disabled={busy !== null || index === brief.intents.length - 1}
                        aria-label={`Move ${intent.label} later`}
                        onClick={() => {
                          setBrief({ ...brief, intents: moveIntent(brief.intents, index, 1) });
                          clearAsked("primary_intent");
                        }}
                      >
                        Later
                      </button>
                    </li>
                  ))}
                </ol>
              </div>
              {showCheck ? (
                <button type="button" onClick={() => void checkPlace()}>
                  Check this place
                </button>
              ) : null}
              {showFind ? (
                <div className="find-row">
                  <p id={findNoteId}>
                    {plan
                      ? "This looks up live places again for this evening."
                      : "This looks up live places for this evening."}
                  </p>
                  <button
                    type="button"
                    aria-describedby={findNoteId}
                    onClick={() => void findPlan()}
                  >
                    {plan ? "Find the plan again" : "Find the plan"}
                  </button>
                </div>
              ) : null}
            </section>
          ) : null}
          {plan ? <PlanResult plan={plan} /> : null}
        </section>

        <section className="examples" aria-labelledby="examples-heading">
          <h2 id="examples-heading">Try an evening</h2>
          <ul>
            {EXAMPLE_EVENINGS.map((prompt) => (
              <li key={prompt}>
                <button
                  type="button"
                  onClick={() => {
                    setEvening(prompt);
                    setComposerError(null);
                    document.getElementById("evening")?.focus();
                  }}
                >
                  {prompt}
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="steps" aria-labelledby="steps-heading">
          <h2 id="steps-heading">How it works</h2>
          <ol>
            <li>You describe one evening.</li>
            <li>If the place, the date, or the time is missing, Happen asks one question.</li>
            <li>The plan stays inside that evening and uses at most two stops.</li>
          </ol>
        </section>
      </main>
      <footer className="trust">
        <h2>Live evidence</h2>
        <p>
          Place evidence comes from live SerpApi results for that evening. Gemma runs locally to
          read the request. Happen does not claim it can plan every city or every night.
        </p>
      </footer>
    </div>
  );
}

function budgetFrom(
  brief: PlanningBrief,
  amount: string,
  currency: string,
): PlanningBrief["budget"] {
  const trimmedAmount = amount.trim();
  const trimmedCurrency = currency.trim().toUpperCase();
  if (!trimmedAmount && !trimmedCurrency) {
    if (brief.budget?.tier && brief.budget.amount === null) {
      return brief.budget;
    }
    return null;
  }
  return {
    amount: trimmedAmount,
    currency: trimmedCurrency,
    tier: brief.budget?.tier ?? null,
    bound: brief.budget?.bound ?? "about",
  };
}

function PlanResult({ plan }: { plan: EveningPlan }) {
  const lead = outcomeLead(plan.outcome);
  const notes = plan.warnings.filter((note) => visibleWarning(note) && note !== lead);
  return (
    <section className="plan" aria-labelledby="plan-heading">
      <h2 id="plan-heading">This evening</h2>
      {lead ? <p>{lead}</p> : null}
      {plan.stops.length > 0 ? (
        <ol>
          {plan.stops.map((stop) => (
            <li key={stop.position}>
              <h3>{`${stop.position}. ${stop.name}`}</h3>
              <p>{stop.explanation}</p>
              <p>
                {stop.hours_status === "unknown"
                  ? "Opening hours were not listed."
                  : "Opening hours cover this arrival."}
              </p>
              {stop.unknown_fields.includes("price") ? <p>Price was not listed.</p> : null}
              {stop.evidence.length > 0 ? (
                <ul>
                  {stop.evidence.map((item) => (
                    <li key={`${item.source}-${item.retrieved_at}-${item.text}`}>
                      {SOURCE_LABEL[item.source]}: {item.text}
                    </li>
                  ))}
                </ul>
              ) : null}
              {stop.warnings.filter(visibleWarning).map((note) => (
                <p key={note}>{note}</p>
              ))}
            </li>
          ))}
        </ol>
      ) : null}
      {plan.transition ? (
        <p>
          Travel time is not verified. <a href={plan.transition.directions_url}>Directions</a>
        </p>
      ) : null}
      {notes.map((note) => (
        <p key={note}>{note}</p>
      ))}
    </section>
  );
}
