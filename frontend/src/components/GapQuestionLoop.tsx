import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { AlreadyAnsweredGap, GapResolutionQuestion, RankedJob } from '../types';

/** What happened to one gap once the candidate had their say. */
export interface GapOutcome {
  gap: string;
  question: string;
  answer: string;
  /** False when the candidate declined — the gap was omitted, not filled. */
  captured: boolean;
}

interface Props {
  job: RankedJob;
  outcomes: GapOutcome[];
  onResolved: (outcome: GapOutcome) => void;
  onFinished: () => void;
}

/**
 * The gap-question loop: one question at a time, the candidate's answer, on
 * to the next.
 *
 * One at a time rather than a form of every question at once, because the
 * loop is a conversation about things the candidate's record does *not*
 * show — a wall of eight "you appear to lack X" prompts reads as a
 * rejection, and the wall is also what makes people pad answers to fill it.
 * The decline button is given equal weight to submitting for the same
 * reason: `GapAnswerPolicy` exists so "nothing to add" cleanly omits the
 * gap, and a UI that hid that option would coax exactly the embellishment
 * the backend refuses to store.
 *
 * Answers are captured against the candidate (not this job): a stored answer
 * suppresses the same gap on later applications, which is why `already`
 * comes back populated on a job whose gaps were met before.
 */
export function GapQuestionLoop({ job, outcomes, onResolved, onFinished }: Props) {
  const [questions, setQuestions] = useState<GapResolutionQuestion[] | null>(null);
  const [already, setAlready] = useState<AlreadyAnsweredGap[]>([]);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const plan = await applyFlowApi.generateGapQuestions(job.gaps);
      setQuestions(plan.questions);
      setAlready(plan.already_answered);
      setIndex(0);
      setAnswer('');
      if (plan.questions.length === 0) onFinished();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  const submit = async (text: string) => {
    const current = questions?.[index];
    if (!current) return;

    setBusy(true);
    setError(null);
    try {
      const resolved = await applyFlowApi.resolveGapAnswer(
        current.gap,
        current.question,
        text,
      );
      onResolved({
        gap: current.gap,
        question: current.question,
        answer: text,
        captured: resolved.captured,
      });
      setAnswer('');
      const next = index + 1;
      setIndex(next);
      if (next >= (questions?.length ?? 0)) onFinished();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  if (job.gaps.length === 0) {
    return (
      <p className="muted">
        No gaps were detected for this role — nothing to ask about.
      </p>
    );
  }

  if (questions === null) {
    return (
      <div className="gap-intro">
        <p>
          This role has {job.gaps.length} gap{job.gaps.length === 1 ? '' : 's'} against
          your profile. Answering them gives the tailored documents real material to
          draw on — anything you skip is simply left out.
        </p>
        <ul className="gap-preview">
          {job.gaps.map((gap) => (
            <li key={gap}>{gap}</li>
          ))}
        </ul>
        {error && <p className="error">{error}</p>}
        <button type="button" onClick={() => void start()} disabled={busy}>
          {busy ? 'Preparing questions…' : 'Start gap questions'}
        </button>
      </div>
    );
  }

  const current = questions[index];
  const done = current === undefined;

  return (
    <div className="gap-loop">
      {already.length > 0 && (
        <div className="notice notice-info">
          <strong>
            {already.length} gap{already.length === 1 ? '' : 's'} skipped
          </strong>{' '}
          — you already answered {already.length === 1 ? 'this' : 'these'} on an earlier
          application, and the stored answer carries over:
          <ul>
            {already.map((entry) => (
              <li key={entry.gap}>{entry.gap}</li>
            ))}
          </ul>
        </div>
      )}

      {!done && (
        <div className="gap-question">
          <p className="gap-progress">
            Question {index + 1} of {questions.length}
          </p>
          <p className="gap-gap">Gap: {current.gap}</p>
          <label htmlFor="gap-answer">{current.question}</label>
          <textarea
            id="gap-answer"
            rows={4}
            value={answer}
            disabled={busy}
            placeholder="Describe real experience, or skip if you have none."
            onChange={(e) => setAnswer(e.target.value)}
          />
          {error && <p className="error">{error}</p>}
          <div className="gap-actions">
            <button
              type="button"
              disabled={busy || answer.trim().length === 0}
              onClick={() => void submit(answer)}
            >
              {busy ? 'Saving…' : 'Save answer'}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => void submit('')}
            >
              Nothing to add — skip
            </button>
          </div>
        </div>
      )}

      {done && (
        <p className="notice notice-ok">
          All {questions.length} question{questions.length === 1 ? '' : 's'} answered.
        </p>
      )}

      {outcomes.length > 0 && (
        <div className="gap-outcomes">
          <span className="section-label">Your answers</span>
          <ul>
            {outcomes.map((outcome) => (
              <li key={outcome.gap}>
                <span className={outcome.captured ? 'pill pill-ok' : 'pill'}>
                  {outcome.captured ? 'captured' : 'skipped'}
                </span>{' '}
                {outcome.gap}
                {outcome.captured && <span className="quiet"> — {outcome.answer}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
