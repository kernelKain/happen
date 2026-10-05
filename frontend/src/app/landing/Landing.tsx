import { useEffect, useId, useRef, useState } from "react";
import type {
  EveningPlan,
  FollowUp,
  PlanningBrief,
  RefinementProposal,
  ResolvedDestination,
} from "../../lib/api/plan";
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
  EVENING_TEXT_LIMIT,
  moveIntent,
  partySizeIssue,
  preferenceIssue,
  preferenceList,
  restorePrompt,
  shouldResolve,
} from "./flow";
import { Mark } from "./Mark";
import { activityLabel, briefSummary, budgetText } from "./present";
import { EveningTimeline, RefinementDiff, SourcesPanel } from "./timeline";
import "./landing.css";

type LandingProps = {
  initialEvening?: string;
  fetchImpl?: PlanFetch;
};

type Busy = "reading" | "checking" | "finding" | "reviewing";

type Failure = {
  message: string;
  next: string;
  retry: "interpret" | "resolve" | "plan" | null;
  live?: boolean;
};

type Stage = "describe" | "review" | "plan";
type View = "plan" | "brief" | "sources";

const BUSY_LABEL: Record<Busy, string> = {
  reading: "Reading your evening…",
  checking: "Finding the destination and its local time through SerpApi…",
  finding: "Checking live listings and opening hours through SerpApi…",
  reviewing: "Reviewing your change…",
};

const STAGES: { id: Stage; label: string }[] = [
  { id: "describe", label: "Describe" },
  { id: "review", label: "Review" },
  { id: "plan", label: "Plan" },
];

const LIVE_FAILURE =
  "We couldn't retrieve a live plan right now. Your evening details are still here.";

/** Customer landing. Place search starts only after Check live places. */
export function Landing({ initialEvening = "", fetchImpl }: LandingProps) {
  const errorId = useId();
  const partyErrorId = useId();
  const budgetErrorId = useId();
  const preferenceErrorId = useId();
  const accessErrorId = useId();
  const dateHintId = useId();
  const findNoteId = useId();
  const alertRef = useRef<HTMLDivElement>(null);
  const followRef = useRef<HTMLInputElement>(null);
  const choiceRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const requestLock = useRef(false);
  // The last question the follow-up form showed, so a new question can clear
  // the draft without the first one erasing an answer already being typed.
  const shownQuestion = useRef<string | null>(null);

  const [evening, setEvening] = useState(initialEvening);
  const [originalPrompt, setOriginalPrompt] = useState<string | null>(null);
  const [brief, setBrief] = useState<PlanningBrief | null>(null);
  const [followUp, setFollowUp] = useState<FollowUp | null>(null);
  const [destination, setDestination] = useState<ResolvedDestination | null>(null);
  const [choices, setChoices] = useState<ResolvedDestination[]>([]);
  // The server issues this when it reads a prompt. It is opaque to the page,
  // and the only thing that identifies this plan's search allowance.
  const [planToken, setPlanToken] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [plan, setPlan] = useState<EveningPlan | null>(null);
  const [proposal, setProposal] = useState<RefinementProposal | null>(null);
  const [revision, setRevision] = useState("");
  const [searchSnapshot, setSearchSnapshot] = useState<PlanningBrief | null>(null);
  const [partyDraft, setPartyDraft] = useState("");
  const [budgetAmount, setBudgetAmount] = useState("");
  const [budgetCurrency, setBudgetCurrency] = useState("");
  const [preferenceDraft, setPreferenceDraft] = useState("");
  const [accessDraft, setAccessDraft] = useState("");
  const [answerDraft, setAnswerDraft] = useState("");
  const [selectedChoice, setSelectedChoice] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [view, setView] = useState<View>("plan");
  const [selectedStop, setSelectedStop] = useState<number | null>(null);
  const sourcesId = useId();
  const briefFieldsId = useId();

  const choosing = choices.length > 0;
  const stage: Stage = plan ? "plan" : brief && originalPrompt ? "review" : "describe";
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
  const accessMessage = preferenceIssue(accessDraft);
  const ready = canFindPlan({
    destination,
    brief,
    followUp: shownFollowUp,
    choosing,
    busy: busy !== null,
  });
  const showFind = ready && failure === null && proposal === null;
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
    // Clear the draft only when the question is actually replaced, never when a
    // first question appears. The draft starts empty, so appearing needs no
    // clearing. Treating the empty state as a prior question made this effect
    // wipe the answer of anyone already typing: the passive effect flushes
    // after the field is on screen, which left the submit button disabled and
    // the answer lost. A truthiness test on the previous question is what
    // distinguishes "no question yet" from "a different question".
    if (shownQuestion.current && shownQuestion.current !== question) {
      setAnswerDraft("");
    }
    shownQuestion.current = question;
    if (question) {
      followRef.current?.focus();
    }
  }, [question]);

  useEffect(() => {
    if (choices.length > 0) {
      choiceRef.current?.focus();
    }
  }, [choices]);

  useEffect(() => {
    if (!plan) {
      setSelectedStop(null);
      setView("plan");
      return;
    }
    setSelectedStop((current) =>
      current !== null && plan.stops.some((stop) => stop.position === current) ? current : null,
    );
  }, [plan]);

  function startOver() {
    cancel();
    setOriginalPrompt(null);
    setBrief(null);
    setFollowUp(null);
    setDestination(null);
    setChoices([]);
    setSelectedChoice(null);
    setPlanToken(null);
    setFailure(null);
    setPlan(null);
    setProposal(null);
    setRevision("");
    setSearchSnapshot(null);
    setEditing(false);
  }

  function viewSources(position: number) {
    setSelectedStop(position);
    setView("sources");
  }

  function closeSources() {
    setSelectedStop(null);
    setView("plan");
  }

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
    // Every brief the server sends carries the plan identity it issued.
    if (next.plan_token) {
      setPlanToken(next.plan_token);
    }
    setPartyDraft(next.party_size === null ? "" : String(next.party_size));
    setBudgetAmount(next.budget?.amount ?? "");
    setBudgetCurrency(next.budget?.currency ?? "");
    setPreferenceDraft(next.preferences.join(", "));
    setAccessDraft(next.accessibility_needs.join(", "));
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
    const live = retry === "plan";
    if (error instanceof PlanRequestError) {
      if (error.status === 500) {
        return {
          message: "Something unexpected happened.",
          next: "Try again.",
          retry: error.retryable ? retry : null,
          live,
        };
      }
      return {
        message: error.message,
        next: error.nextAction,
        retry: error.retryable ? retry : null,
        live,
      };
    }
    return {
      message: "Happen could not be reached.",
      next: "Try again.",
      retry,
      live,
    };
  }

  async function resolveInto(current: PlanningBrief, id: number) {
    const query = current.destination_text?.trim();
    if (!query || id !== generation.current) {
      return;
    }
    const phrase = current.pending_date?.phrase;
    const token = current.plan_token;
    if (!token) {
      setFailure({
        message: "This plan session is no longer valid.",
        next: "Start a new search.",
        retry: null,
      });
      return;
    }
    const resolution = await resolveDestination(
      {
        query,
        pending_date: phrase === "today" || phrase === "tomorrow" ? phrase : undefined,
        local_date: current.local_date,
        local_start: current.local_start,
        plan_token: token,
      },
      { signal: abortRef.current?.signal, fetchImpl },
    );
    if (id !== generation.current) {
      return;
    }
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
      setPlanToken(next.plan_token);
      setPlan(null);
      setProposal(null);
      setSearchSnapshot(null);
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
      // Answering a question continues the same submitted plan, so the server
      // keeps the current token and the allowance it has left.
      const proposal = await refineBrief(restorePrompt(brief, originalPrompt), cleaned, {
        signal: abortRef.current?.signal,
        fetchImpl,
        purpose: "follow_up",
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

  async function findPlan(options?: {
    keepCurrent?: boolean;
    token?: string;
    source?: PlanningBrief;
  }) {
    const source = options?.source ?? brief;
    if (!source || !destination?.timezone_name || !source.local_date || !source.local_start) {
      return;
    }
    // The server is the only authority on the allowance. The page keeps the
    // count it was last told, and the server refuses anything over budget.
    const token = options?.token ?? planToken;
    if (!token) {
      setFailure({
        message: "This plan session is no longer valid.",
        next: "Start a new search.",
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
    if (!options?.keepCurrent) {
      setPlan(null);
    }
    try {
      const eveningPlan = await requestPlan(planQuery(source, destination, token), {
        signal: abortRef.current?.signal,
        fetchImpl,
      });
      if (id !== generation.current) {
        return;
      }
      setPlan(eveningPlan);
      setSearchSnapshot(source);
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

  async function reviewChange(text: string) {
    if (!brief || !originalPrompt) {
      return;
    }
    const cleaned = text.trim();
    if (!cleaned) {
      return;
    }
    if (cleaned.length > EVENING_TEXT_LIMIT) {
      setFailure({
        message: "That change is too long to review.",
        next: "Shorten it and try again.",
        retry: null,
      });
      return;
    }
    const id = begin();
    if (id === null) {
      return;
    }
    setBusy("reviewing");
    setFailure(null);
    try {
      // Reviewing a change after a result is a plan refinement, not a question.
      // The server decides the allowance, and issues a new plan identity when
      // the proposal is applied.
      const next = await refineBrief(restorePrompt(brief, originalPrompt), cleaned, {
        signal: abortRef.current?.signal,
        fetchImpl,
        purpose: "plan_refinement",
      });
      if (id !== generation.current) {
        return;
      }
      setProposal(next);
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

  function cancelProposal() {
    setProposal(null);
    setRevision("");
  }

  async function applyProposal() {
    if (!proposal || !brief || !originalPrompt || proposal.follow_up) {
      return;
    }
    const proposed = restorePrompt(proposal.proposed, originalPrompt);
    const baseline = searchSnapshot ?? brief;
    const samePlace =
      (baseline.destination_text ?? "").trim() === (proposed.destination_text ?? "").trim();
    const id = begin();
    if (id === null) {
      return;
    }
    // The visible brief and the plan stay as they are until the recomputation
    // has actually succeeded or has returned an explicit evidence outcome.
    try {
      let place = destination;
      // An accepted refinement is a newly submitted plan, so the server issues
      // it its own plan identity and a fresh allowance. Apply uses the token
      // that came back with the proposal, never the one the page was holding.
      const token = proposed.plan_token ?? planToken;
      if (!samePlace || !place?.timezone_name) {
        const query = proposed.destination_text?.trim();
        if (!query || !proposed.local_date || !proposed.local_start) {
          return;
        }
        if (!token) {
          setFailure({
            message: "This plan session is no longer valid.",
            next: "Start a new search.",
            retry: null,
          });
          return;
        }
        setBusy("checking");
        const phrase = proposed.pending_date?.phrase;
        const resolution = await resolveDestination(
          {
            query,
            pending_date: phrase === "today" || phrase === "tomorrow" ? phrase : undefined,
            local_date: proposed.local_date,
            local_start: proposed.local_start,
            plan_token: token,
          },
          { signal: abortRef.current?.signal, fetchImpl },
        );
        if (id !== generation.current) {
          return;
        }
        if (resolution.status === "ambiguous") {
          setDestination(null);
          setSelectedChoice(null);
          setChoices(resolution.choices);
          return;
        }
        if (resolution.status !== "resolved" || !resolution.destination?.timezone_name) {
          setFailure({
            message: "Happen could not place that destination in a local time.",
            next: "Choose a different place.",
            retry: null,
          });
          return;
        }
        place = resolution.destination;
        setDestination(place);
        setChoices([]);
      }
      if (!place?.timezone_name || !proposed.local_date || !proposed.local_start) {
        return;
      }
      if (!token) {
        setFailure({
          message: "This plan session is no longer valid.",
          next: "Start a new search.",
          retry: null,
        });
        return;
      }
      setBusy("finding");
      // The whole proposed brief goes to the server. Python revalidates it and
      // decides whether the cached evidence is enough or a new retrieval is due.
      const eveningPlan = await requestPlan(planQuery(proposed, place, token), {
        signal: abortRef.current?.signal,
        fetchImpl,
      });
      if (id !== generation.current) {
        return;
      }
      rememberBrief(proposed);
      setPlanToken(proposed.plan_token);
      setPlan(eveningPlan);
      setSearchSnapshot(proposed);
      setProposal(null);
      setRevision("");
    } catch (error) {
      if (id !== generation.current) {
        return;
      }
      // The previous brief and the previous plan both stay visible.
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
    if (cleaned.length > EVENING_TEXT_LIMIT) {
      setComposerError("That evening is too long to plan.");
      return;
    }
    void interpretPrompt(cleaned);
  }

  const needsAttention = Boolean(
    brief &&
      (!brief.destination_text?.trim() ||
        !brief.local_date ||
        !brief.local_start ||
        brief.intents.length === 0 ||
        partyMessage ||
        budgetMessage ||
        preferenceMessage ||
        accessMessage),
  );
  const formOpen = editing || needsAttention;
  const summary = brief ? briefSummary(brief, destination) : null;
  const sourceStop =
    plan && selectedStop !== null
      ? (plan.stops.find((stop) => stop.position === selectedStop) ?? null)
      : null;

  const statusAndNotice = (
    <>
      {busy ? (
        <div className="status-row status-live">
          <p className="held" role="status">
            {BUSY_LABEL[busy]}
          </p>
          <button type="button" className="secondary" onClick={cancel}>
            Cancel
          </button>
        </div>
      ) : null}
      {failure ? (
        <div className="notice" role="alert" tabIndex={-1} ref={alertRef}>
          {failure.live ? <p className="notice-lead">{LIVE_FAILURE}</p> : null}
          <p>{failure.message}</p>
          <p>{failure.next}</p>
          {failure.retry ? (
            <button type="button" onClick={retry} disabled={busy !== null}>
              Try again
            </button>
          ) : null}
        </div>
      ) : null}
    </>
  );

  const questions = (
    <>
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
    </>
  );

  return (
    <div className="landing" data-stage={stage}>
      <a className="skip" href={stage === "describe" ? "#evening" : "#workspace"}>
        {stage === "describe" ? "Skip to the evening" : "Skip to your plan"}
      </a>
      <header className={stage === "describe" ? "landing-bar" : "landing-bar app-bar"}>
        <p className="brand">
          <Mark />
          <span className="wordmark">Happen</span>
        </p>
        {stage !== "describe" ? (
          <>
            <ol className="progress" aria-label="Progress">
              {STAGES.map((item, index) => {
                const current = STAGES.findIndex((entry) => entry.id === stage);
                return (
                  <li
                    key={item.id}
                    aria-current={item.id === stage ? "step" : undefined}
                    data-done={index < current}
                  >
                    {item.label}
                  </li>
                );
              })}
            </ol>
            <button type="button" className="secondary new-evening" onClick={startOver}>
              New evening
            </button>
          </>
        ) : null}
      </header>
      <main>
        {stage === "describe" ? (
          <>
            <section className="landing-hero" aria-labelledby="promise">
              <div className="promise">
                <h1 id="promise">Turn your evening into a checked plan.</h1>
                <p>
                  Describe your evening. Happen checks live place listings and returns one
                  source-backed plan with up to two stops.
                </p>
              </div>
              <form
                className="composer"
                onSubmit={(event) => {
                  event.preventDefault();
                  submitComposer(evening);
                }}
              >
                <label htmlFor="evening">What would you like to do?</label>
                <textarea
                  id="evening"
                  name="evening"
                  rows={4}
                  maxLength={EVENING_TEXT_LIMIT}
                  value={evening}
                  disabled={busy !== null}
                  aria-invalid={composerError !== null}
                  aria-describedby={composerError ? `${errorId} ${findNoteId}` : findNoteId}
                  placeholder="Coffee in Mexico City on Wednesday at 6 pm, then a museum, for two."
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
                <div className="composer-actions">
                  <button type="submit" disabled={busy !== null}>
                    Build my evening
                  </button>
                  <p id={findNoteId} className="composer-note">
                    Searches live place listings through SerpApi when you continue.
                  </p>
                </div>
                <ul className="chips" aria-label="Example evenings">
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
              </form>
              <TrustStrip />
            </section>
            <section className="flow" aria-label="Planning status" aria-busy={busy !== null}>
              {statusAndNotice}
            </section>
            <section className="different" aria-labelledby="different-heading">
              <h2 id="different-heading">Built to finish the decision</h2>
              <p>
                General chat helps you explore possibilities. Happen narrows them into one feasible
                sequence, shows what was checked, and keeps unsupported details unknown.
              </p>
            </section>
          </>
        ) : (
          <div
            id="workspace"
            className="workspace"
            data-stage={stage}
            data-view={view}
            data-sources={sourceStop ? "open" : "closed"}
            tabIndex={-1}
          >
            <h1 className="visually-hidden">
              {stage === "plan" ? "Your evening plan" : "Review your evening"}
            </h1>
            <section className="flow" aria-label="Planning status" aria-busy={busy !== null}>
              {statusAndNotice}
            </section>
            {plan ? (
              <nav className="view-switch" aria-label="Plan sections">
                {(["plan", "brief", "sources"] as const).map((item) => (
                  <button
                    key={item}
                    type="button"
                    aria-pressed={view === item}
                    onClick={() => {
                      if (item === "sources" && selectedStop === null) {
                        setSelectedStop(plan.stops[0]?.position ?? null);
                      }
                      setView(item);
                    }}
                    disabled={item === "sources" && plan.stops.length === 0}
                  >
                    {item === "plan" ? "Plan" : item === "brief" ? "Brief" : "Sources"}
                  </button>
                ))}
              </nav>
            ) : null}
            <aside className="rail" aria-label="Your evening brief">
              {questions}
              {brief && summary ? (
                <section className="brief" aria-labelledby="brief-heading">
                  <h2 id="brief-heading">Your evening</h2>
                  <p className="original">Your words: {originalPrompt}</p>
                  <div className="brief-summary">
                    <p className="brief-line-main">
                      {summary.where}
                      {" · "}
                      {brief.local_date ? (
                        <time dateTime={brief.local_date}>{summary.when[0]}</time>
                      ) : (
                        summary.when[0]
                      )}
                      {" · "}
                      {brief.local_start ? (
                        <time dateTime={brief.local_start.slice(0, 5)}>{summary.when[1]}</time>
                      ) : (
                        summary.when[1]
                      )}
                    </p>
                    <p>{summary.details.join(" · ")}</p>
                    {summary.extras.map((line) => (
                      <p key={line}>{line}</p>
                    ))}
                    {summary.zone ? <p className="brief-zone">{summary.zone}</p> : null}
                    {brief.pending_date && !brief.local_date ? (
                      <p className="field-hint">
                        You said {brief.pending_date.phrase.replaceAll("_", " ")}.
                      </p>
                    ) : null}
                  </div>
                  {!needsAttention ? (
                    <button
                      type="button"
                      className="secondary"
                      aria-expanded={formOpen}
                      aria-controls={briefFieldsId}
                      onClick={() => setEditing((current) => !current)}
                    >
                      {editing ? "Done editing" : "Edit details"}
                    </button>
                  ) : null}
                  {formOpen ? (
                    <div id={briefFieldsId} className="brief-form">
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
                            Pick the calendar date for “
                            {brief.pending_date.phrase.replaceAll("_", " ")}”.
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
                              setBrief({
                                ...brief,
                                budget: budgetFrom(brief, amount, budgetCurrency),
                              });
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
                              setBrief({
                                ...brief,
                                budget: budgetFrom(brief, budgetAmount, currency),
                              });
                            }}
                          />
                        </label>
                        <label className="brief-span">
                          Accessibility
                          <input
                            value={accessDraft}
                            disabled={busy !== null}
                            aria-invalid={accessMessage !== null}
                            aria-describedby={accessMessage ? accessErrorId : undefined}
                            onChange={(event) => {
                              const value = event.target.value;
                              setAccessDraft(value);
                              if (preferenceIssue(value)) {
                                return;
                              }
                              setBrief({ ...brief, accessibility_needs: preferenceList(value) });
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
                      {accessMessage ? (
                        <p id={accessErrorId} className="composer-error" role="alert">
                          {accessMessage}
                        </p>
                      ) : null}
                      {preferenceMessage ? (
                        <p id={preferenceErrorId} className="composer-error" role="alert">
                          {preferenceMessage}
                        </p>
                      ) : null}
                      {brief.budget?.tier ? (
                        <p>Price range: {budgetText({ ...brief.budget, amount: null })}.</p>
                      ) : null}
                      <div className="intent-order">
                        <h3>Stop order</h3>
                        {brief.intents.length === 0 ? <p>No stop is listed yet.</p> : null}
                        <ol>
                          {brief.intents.map((intent, index) => (
                            <li key={`${intent.kind}-${intent.label}`}>
                              <span>{`${intent.position}. ${activityLabel(intent.kind, intent.label)}`}</span>
                              <button
                                type="button"
                                className="secondary"
                                disabled={busy !== null || index === 0}
                                aria-label={`Move ${intent.label} earlier`}
                                onClick={() => {
                                  setBrief({
                                    ...brief,
                                    intents: moveIntent(brief.intents, index, -1),
                                  });
                                  clearAsked("primary_intent");
                                }}
                              >
                                Earlier
                              </button>
                              <button
                                type="button"
                                className="secondary"
                                disabled={busy !== null || index === brief.intents.length - 1}
                                aria-label={`Move ${intent.label} later`}
                                onClick={() => {
                                  setBrief({
                                    ...brief,
                                    intents: moveIntent(brief.intents, index, 1),
                                  });
                                  clearAsked("primary_intent");
                                }}
                              >
                                Later
                              </button>
                            </li>
                          ))}
                        </ol>
                      </div>
                    </div>
                  ) : null}
                  {showCheck ? (
                    <button type="button" onClick={() => void checkPlace()}>
                      Check this place
                    </button>
                  ) : null}
                  {showFind ? (
                    <div className="find-row">
                      <button
                        type="button"
                        aria-describedby={`${findNoteId}-brief`}
                        onClick={() => {
                          setEditing(false);
                          setView("plan");
                          void findPlan();
                        }}
                      >
                        {plan ? "Check live places again" : "Check live places"}
                      </button>
                      <p id={`${findNoteId}-brief`} className="composer-note">
                        {plan
                          ? "This refreshes the live place evidence through SerpApi."
                          : "This searches live place listings through SerpApi."}
                      </p>
                    </div>
                  ) : null}
                </section>
              ) : null}
              {plan && brief && !proposal ? (
                <form
                  className="refine"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void reviewChange(revision);
                  }}
                >
                  <label htmlFor="revision">Change this evening</label>
                  <textarea
                    id="revision"
                    rows={2}
                    maxLength={EVENING_TEXT_LIMIT}
                    value={revision}
                    disabled={busy !== null}
                    placeholder="Make it for four people."
                    onChange={(event) => setRevision(event.target.value)}
                  />
                  <button type="submit" disabled={busy !== null || revision.trim() === ""}>
                    Review this change
                  </button>
                </form>
              ) : null}
              {proposal ? (
                <RefinementDiff
                  proposal={proposal}
                  busy={busy !== null}
                  onApply={() => void applyProposal()}
                  onCancel={cancelProposal}
                />
              ) : null}
            </aside>
            <section className="stage-main" aria-label="Plan">
              {plan ? (
                <EveningTimeline
                  plan={plan}
                  brief={searchSnapshot ?? brief}
                  destination={destination}
                  intentCount={
                    searchSnapshot?.intents.length ?? brief?.intents.length ?? plan.stops.length
                  }
                  sourcesId={sourcesId}
                  selectedStop={selectedStop}
                  onViewSources={viewSources}
                />
              ) : (
                <ReviewGuide ready={showFind} busy={busy === "finding"} />
              )}
            </section>
            {plan && sourceStop ? (
              <SourcesPanel
                key={sourceStop.position}
                id={sourcesId}
                stop={sourceStop}
                plan={plan}
                brief={searchSnapshot ?? brief}
                timezone={destination?.timezone_name ?? null}
                onClose={closeSources}
              />
            ) : null}
          </div>
        )}
      </main>
      <Methodology />
    </div>
  );
}

/** What happens next while the visitor reviews the brief. Nothing here is a result. */
function ReviewGuide({ ready, busy }: { ready: boolean; busy: boolean }) {
  return (
    <div className="review-guide">
      <h2>{busy ? "Checking live places" : "Next: check live places"}</h2>
      <ol>
        <li>Happen searches live place listings through SerpApi for this evening.</li>
        <li>Python checks opening hours and your requested details for each place.</li>
        <li>You get at most two stops, with anything unconfirmed clearly marked.</li>
      </ol>
      {!ready && !busy ? <p>Answer the question or complete the brief to continue.</p> : null}
    </div>
  );
}

/**
 * The three claims the product makes about itself, above the fold.
 *
 * Each one is a promise the reader can hold the plan to, not an implementation
 * detail. Anything about how Happen is built belongs in the methodology drawer
 * instead of here.
 */
function TrustStrip() {
  return (
    <ul className="trust-strip">
      <li>
        <strong>Live when you search</strong>
        <span>Place listings are retrieved through SerpApi for this evening.</span>
      </li>
      <li>
        <strong>Feasibility first</strong>
        <span>Opening hours and requested constraints are checked before a stop is chosen.</span>
      </li>
      <li>
        <strong>No hidden guesses</strong>
        <span>Anything the sources do not confirm is clearly marked.</span>
      </li>
    </ul>
  );
}

/**
 * Methodology, kept out of the primary journey.
 *
 * This is a disclosure rather than a page, so the explanation of how Happen
 * works is available without competing with the decision the visitor came to
 * make. It stays closed until it is asked for, and it is reachable by keyboard.
 */
function Methodology() {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <footer className="methodology">
      <button
        type="button"
        className="methodology-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(!open)}
      >
        {open ? "Hide how Happen decides" : "How Happen decides"}
      </button>
      {open ? (
        <div id={panelId} className="methodology-body">
          <p>
            Describe one evening in your own words. If the place, the date, or the time is missing,
            Happen asks one question before it searches.
          </p>
          <p>
            Place evidence comes from live SerpApi results for that evening. Your request is read by
            local deterministic parsing, and Python checks feasibility and picks the stops. A plan
            holds at most two stops for that one evening, and it does not span multiple dates.
          </p>
          <p>
            A local Gemma model was measured here and missed its quality gates, so it stays switched
            off. Happen does not claim it can plan every city or every night. When the retrieval
            does not support a fact, the result says it is unknown.
          </p>
        </div>
      ) : null}
    </footer>
  );
}

function planQuery(source: PlanningBrief, destination: ResolvedDestination, token: string) {
  return {
    destination,
    intents: source.intents,
    local_date: source.local_date ?? "",
    local_start: source.local_start ?? "",
    party_size: source.party_size,
    budget: source.budget,
    preferences: source.preferences,
    accessibility_needs: source.accessibility_needs,
    plan_token: token,
  };
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
