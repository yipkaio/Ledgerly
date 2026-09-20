import { useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  Lightbulb,
  LoaderCircle,
  MessageCircleQuestion,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Notice } from "@/components/feedback";
import { message, request } from "@/lib/api";

type Audit = {
  request_id: string;
  task: string;
  model: string;
  prompt_version: string;
  input_sha256: string;
  cached: boolean;
  created_at: string;
};
type Explanation = {
  executive_summary: string;
  exceptions: {
    exception_type: string;
    priority: "low" | "medium" | "high";
    explanation: string;
    next_action: string;
    evidence_ids: string[];
  }[];
  limitations: string[];
  advisory_only: true;
};
type Brief = {
  close_status: "ready" | "attention_required" | "insufficient_evidence";
  highlights: string[];
  attention_items: string[];
  checklist: string[];
  caveat: string;
  advisory_only: true;
};
type Answer = {
  answer: string;
  evidence: string[];
  limitations: string[];
  advisory_only: true;
};
type Result =
  | { kind: "explanation"; data: Explanation; audit: Audit; fallback: boolean }
  | { kind: "brief"; data: Brief; audit: Audit; fallback: boolean }
  | { kind: "answer"; data: Answer; audit: Audit; fallback: boolean };

type SuggestedQuestion = {
  label: string;
  question: string;
  icon: typeof Lightbulb;
};

export function FinanceCopilot({
  token,
  month,
  currency,
  exceptionCount = 0,
  matchedPercent = 0,
  statementCount = 0,
}: {
  token: string;
  month: string;
  currency: string;
  exceptionCount?: number;
  matchedPercent?: number;
  statementCount?: number;
}) {
  const [busy, setBusy] = useState<"explain" | "brief" | "ask" | null>(null);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  const suggestedQuestions: SuggestedQuestion[] = [
    exceptionCount
      ? {
          label: "Prioritise exceptions",
          question: "Which reconciliation exceptions should I resolve first?",
          icon: AlertTriangle,
        }
      : {
          label: "Check close readiness",
          question: "Is this monthly close ready based on the recorded evidence?",
          icon: CheckCircle2,
        },
    {
      label: "Find missing evidence",
      question: "Which bank debits are missing receipt evidence?",
      icon: FileSearch,
    },
    matchedPercent < 100
      ? {
          label: "Understand coverage",
          question: `Why is only ${matchedPercent}% of accepted receipt spend matched?`,
          icon: Lightbulb,
        }
      : {
          label: "Review matched spend",
          question: "What does the matched receipt evidence show for this month?",
          icon: Lightbulb,
        },
    {
      label: "Prepare for close",
      question: "What should I verify for the monthly close?",
      icon: ClipboardCheck,
    },
  ];

  async function run(kind: "explain" | "brief" | "ask") {
    if (kind === "ask" && question.trim().length < 5) return;
    setBusy(kind);
    setError("");
    setResult(null);
    try {
      const body = { month, currency, ...(kind === "ask" ? { question: question.trim() } : {}) };
      const endpoint =
        kind === "explain"
          ? "/ai/reconciliation/explain"
          : kind === "brief"
            ? "/ai/monthly-close/brief"
            : "/ai/copilot/ask";
      const response = await request<Record<string, unknown>>(endpoint, token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        timeoutMs: 120000,
      });
      const fallback = response.fallback === true;
      if (kind === "explain")
        setResult({
          kind: "explanation",
          data: response.explanation as Explanation,
          audit: response.audit as Audit,
          fallback,
        });
      else if (kind === "brief")
        setResult({
          kind,
          data: response.brief as Brief,
          audit: response.audit as Audit,
          fallback,
        });
      else
        setResult({
          kind: "answer",
          data: response.answer as Answer,
          audit: response.audit as Audit,
          fallback,
        });
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      className="overflow-hidden rounded-2xl border border-emerald-200 bg-white shadow-[0_18px_50px_-30px_rgba(23,63,49,0.7)]"
      aria-labelledby="finance-copilot-title"
    >
      <div className="relative overflow-hidden bg-gradient-to-br from-emerald-950 via-emerald-900 to-teal-700 px-5 py-6 text-white sm:px-7 sm:py-7">
        <div
          aria-hidden="true"
          className="absolute -top-20 -right-16 size-56 rounded-full border border-white/10 bg-white/5"
        />
        <div
          aria-hidden="true"
          className="absolute -right-4 -bottom-24 size-48 rounded-full border border-white/10"
        />
        <div className="relative flex flex-wrap items-start justify-between gap-5">
          <div className="max-w-2xl">
            <div className="mb-3 flex items-center gap-2 text-xs font-semibold tracking-[0.16em] text-emerald-100 uppercase">
              <Sparkles className="size-4" />
              AI-assisted month-end review
            </div>
            <div className="flex items-center gap-3">
              <span className="rounded-2xl border border-white/15 bg-white/10 p-3 shadow-inner">
                <Bot className="size-7" />
              </span>
              <div>
                <h2 id="finance-copilot-title" className="text-2xl font-semibold tracking-tight">
                  Finance Copilot
                </h2>
                <p className="mt-1 text-sm text-emerald-50/80">
                  Turn this month&apos;s reconciliation into clear next steps.
                </p>
              </div>
            </div>
          </div>
          <span className="flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-medium text-emerald-50 backdrop-blur">
            <ShieldCheck className="size-3.5" />
            Read-only advisory
          </span>
        </div>
        <div className="relative mt-6 flex flex-wrap gap-2 text-xs">
          <ContextPill label="Period" value={month} />
          <ContextPill label="Currency" value={currency} />
          <ContextPill
            label="Exceptions"
            value={String(exceptionCount)}
            tone={exceptionCount ? "warning" : "success"}
          />
          <ContextPill label="Matched" value={`${matchedPercent}%`} tone="success" />
        </div>
      </div>

      <div className="grid gap-6 p-5 sm:p-7 xl:grid-cols-[0.9fr_1.1fr]">
        <div>
          <div>
            <p className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
              Quick actions
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <QuickAction
                title="Explain exceptions"
                description={
                  exceptionCount
                    ? `Summarise and prioritise ${exceptionCount} recorded issue${exceptionCount === 1 ? "" : "s"}.`
                    : "Confirm what the reconciliation currently shows."
                }
                icon={FileSearch}
                busy={busy === "explain"}
                disabled={busy !== null}
                onClick={() => void run("explain")}
              />
              <QuickAction
                title="Build close brief"
                description="Create a concise status, attention list, and human checklist."
                icon={ClipboardCheck}
                busy={busy === "brief"}
                disabled={busy !== null}
                onClick={() => void run("brief")}
              />
            </div>
          </div>

          <div className="mt-6">
            <div className="flex items-end justify-between gap-3">
              <div>
                <p className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                  Suggested questions
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Select one to place it in the question box.
                </p>
              </div>
            </div>
            <div className="mt-3 space-y-2">
              {suggestedQuestions.map((item) => {
                const Icon = item.icon;
                const selected = question === item.question;
                return (
                  <button
                    key={item.question}
                    type="button"
                    disabled={busy !== null}
                    aria-pressed={selected}
                    onClick={() => {
                      setQuestion(item.question);
                      setError("");
                    }}
                    className={`group flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
                      selected
                        ? "border-emerald-500 bg-emerald-50 shadow-sm"
                        : "bg-white hover:-translate-y-0.5 hover:border-emerald-300 hover:shadow-sm"
                    }`}
                  >
                    <span
                      className={`rounded-lg p-2 transition-colors ${
                        selected
                          ? "bg-emerald-600 text-white"
                          : "bg-emerald-50 text-emerald-700 group-hover:bg-emerald-100"
                      }`}
                    >
                      <Icon className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">{item.label}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {item.question}
                      </span>
                    </span>
                    <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="rounded-2xl border bg-gradient-to-b from-emerald-50/70 to-white p-4 sm:p-5">
          <div className="flex items-start gap-3">
            <span className="rounded-xl bg-emerald-100 p-2 text-emerald-800">
              <MessageCircleQuestion className="size-5" />
            </span>
            <div>
              <h3 className="font-semibold">Ask about this period</h3>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Answers use only the selected month&apos;s recorded evidence.
              </p>
            </div>
          </div>

          <form
            className="mt-4"
            onSubmit={(event) => {
              event.preventDefault();
              void run("ask");
            }}
          >
            <label className="sr-only" htmlFor="copilot-question">
              Ask Finance Copilot
            </label>
            <Textarea
              id="copilot-question"
              minLength={5}
              maxLength={500}
              rows={4}
              disabled={busy !== null}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              className="min-h-28 resize-none bg-white leading-6 shadow-sm"
              placeholder={
                statementCount
                  ? "Ask about unmatched debits, missing receipts, payment status, or close readiness…"
                  : "Ask what evidence is missing before this month can be closed…"
              }
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="max-w-sm text-xs text-muted-foreground">
                Unrelated questions and requests for secrets or system instructions are refused.
              </p>
              <Button
                size="lg"
                className="min-w-28 rounded-xl shadow-sm"
                disabled={busy !== null || question.trim().length < 5}
              >
                {busy === "ask" ? (
                  <LoaderCircle className="animate-spin" />
                ) : (
                  <Sparkles />
                )}
                {busy === "ask" ? "Thinking…" : "Ask Copilot"}
              </Button>
            </div>
          </form>

          {error && (
            <div className="mt-4">
              <Notice variant="destructive">{error}</Notice>
            </div>
          )}
          {result && <CopilotResult result={result} />}
        </div>
      </div>
    </section>
  );
}

function ContextPill({
  label,
  value,
  tone = "plain",
}: {
  label: string;
  value: string;
  tone?: "plain" | "success" | "warning";
}) {
  const tones = {
    plain: "border-white/15 bg-white/10 text-emerald-50",
    success: "border-emerald-300/20 bg-emerald-300/10 text-emerald-50",
    warning: "border-amber-200/25 bg-amber-300/15 text-amber-50",
  };
  return (
    <span className={`rounded-full border px-3 py-1.5 ${tones[tone]}`}>
      <span className="opacity-70">{label}</span>
      <strong className="ml-1.5 font-semibold">{value}</strong>
    </span>
  );
}

function QuickAction({
  title,
  description,
  icon: Icon,
  busy,
  disabled,
  onClick,
}: {
  title: string;
  description: string;
  icon: typeof FileSearch;
  busy: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="group flex min-h-28 items-start gap-3 rounded-xl border bg-muted/20 p-4 text-left transition-all hover:-translate-y-0.5 hover:border-emerald-300 hover:bg-emerald-50/60 hover:shadow-sm disabled:cursor-not-allowed disabled:opacity-50"
    >
      <span className="rounded-xl bg-emerald-100 p-2.5 text-emerald-800 transition-colors group-hover:bg-emerald-600 group-hover:text-white">
        {busy ? <LoaderCircle className="size-5 animate-spin" /> : <Icon className="size-5" />}
      </span>
      <span>
        <span className="flex items-center gap-2 font-semibold">
          {title}
          <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
        </span>
        <span className="mt-1 block text-xs leading-5 text-muted-foreground">{description}</span>
      </span>
    </button>
  );
}

function CopilotResult({ result }: { result: Result }) {
  return (
    <div className="mt-5 border-t border-emerald-100 pt-5" aria-live="polite">
      {result.fallback && (
        <p className="mb-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          The AI response could not be safely used. This result comes from recorded totals and
          statuses only.
        </p>
      )}

      {result.kind === "explanation" ? (
        <>
          <ResultTitle icon={FileSearch} title="Exception explanation" />
          <p className="mt-3 rounded-xl border bg-white p-4 text-sm leading-6 shadow-sm">
            {result.data.executive_summary}
          </p>
          {!!result.data.exceptions.length && (
            <div className="mt-4 space-y-3">
              {result.data.exceptions.map((item, index) => (
                <article
                  key={`${item.exception_type}-${index}`}
                  className="rounded-xl border bg-white p-4 shadow-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium">{item.exception_type}</p>
                    <PriorityBadge priority={item.priority} />
                  </div>
                  <p className="mt-2 text-sm leading-6">{item.explanation}</p>
                  <div className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-950">
                    <strong>Next step:</strong> {item.next_action}
                  </div>
                </article>
              ))}
            </div>
          )}
          <List title="Limitations" items={result.data.limitations} />
        </>
      ) : result.kind === "brief" ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <ResultTitle icon={ClipboardCheck} title="Monthly-close brief" />
            <StatusBadge status={result.data.close_status} />
          </div>
          <List title="Highlights" items={result.data.highlights} />
          <List title="Needs attention" items={result.data.attention_items} tone="warning" />
          <List title="Human checklist" items={result.data.checklist} ordered />
          <p className="mt-4 text-xs leading-5 text-muted-foreground">{result.data.caveat}</p>
        </>
      ) : (
        <>
          <ResultTitle icon={Bot} title="Copilot answer" />
          <p className="mt-3 whitespace-pre-wrap rounded-xl border bg-white p-4 text-sm leading-6 shadow-sm">
            {result.data.answer}
          </p>
          <List title="Evidence used" items={result.data.evidence} />
          <List title="Limitations" items={result.data.limitations} />
        </>
      )}

      <p className="mt-4 border-t pt-3 text-[11px] text-muted-foreground">
        {result.fallback
          ? "Deterministic fallback · no AI interpretation used"
          : result.audit.cached
            ? "Cached result"
            : "New model call"}{" "}
        · prompt {result.audit.prompt_version} · request {result.audit.request_id.slice(0, 8)}
      </p>
    </div>
  );
}

function ResultTitle({ icon: Icon, title }: { icon: typeof Bot; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="rounded-lg bg-emerald-100 p-1.5 text-emerald-800">
        <Icon className="size-4" />
      </span>
      <h3 className="font-semibold">{title}</h3>
    </div>
  );
}

function PriorityBadge({ priority }: { priority: "low" | "medium" | "high" }) {
  const tones = {
    low: "bg-slate-100 text-slate-700",
    medium: "bg-amber-100 text-amber-900",
    high: "bg-red-100 text-red-800",
  };
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${tones[priority]}`}>
      {priority} priority
    </span>
  );
}

function StatusBadge({ status }: { status: Brief["close_status"] }) {
  const tones = {
    ready: "bg-emerald-100 text-emerald-800",
    attention_required: "bg-amber-100 text-amber-900",
    insufficient_evidence: "bg-slate-100 text-slate-700",
  };
  return (
    <span className={`rounded-full px-3 py-1.5 text-xs font-semibold capitalize ${tones[status]}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

function List({
  title,
  items,
  ordered = false,
  tone = "plain",
}: {
  title: string;
  items: string[];
  ordered?: boolean;
  tone?: "plain" | "warning";
}) {
  if (!items.length) return null;
  const Tag = ordered ? "ol" : "ul";
  return (
    <div className="mt-4">
      <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h4>
      <Tag
        className={`mt-2 space-y-2 rounded-xl border p-4 pl-9 text-sm leading-5 ${
          ordered ? "list-decimal" : "list-disc"
        } ${tone === "warning" ? "border-amber-200 bg-amber-50/70" : "bg-white"}`}
      >
        {items.map((item, index) => (
          <li key={`${index}-${item}`}>{item}</li>
        ))}
      </Tag>
    </div>
  );
}
