import { useId, useState } from "react";
import { EXAMPLE_EVENINGS } from "./examples";
import { Mark } from "./Mark";
import "./landing.css";

type LandingProps = {
  initialEvening?: string;
};

/** Customer landing. It collects one evening and does not invent a plan. */
export function Landing({ initialEvening = "" }: LandingProps) {
  const errorId = useId();
  const [evening, setEvening] = useState(initialEvening);
  const [held, setHeld] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function holdEvening(value: string) {
    const cleaned = value.trim();
    if (!cleaned) {
      setHeld(null);
      setError("Describe the evening before Happen can plan it.");
      return;
    }
    setError(null);
    setHeld(cleaned);
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
              holdEvening(evening);
            }}
          >
            <label htmlFor="evening">Describe the evening</label>
            <textarea
              id="evening"
              name="evening"
              rows={5}
              value={evening}
              aria-invalid={error !== null}
              aria-describedby={error ? errorId : undefined}
              placeholder="Dinner in Kyoto tomorrow at 7, then a short walk."
              onChange={(event) => {
                setEvening(event.target.value);
                if (error) {
                  setError(null);
                }
              }}
            />
            {error ? (
              <p id={errorId} className="composer-error" role="alert">
                {error}
              </p>
            ) : null}
            <button type="submit">Plan this evening</button>
            {held ? (
              <p className="held" role="status">
                Happen will plan this evening: {held}
              </p>
            ) : null}
          </form>
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
                    setError(null);
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
