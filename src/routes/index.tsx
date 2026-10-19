import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Agent Intent Verifier — GenLayer Intelligent Contract" },
      {
        name: "description",
        content:
          "Contract-only GenLayer Intelligent Contract repository. No frontend — deploy contracts/agent_intent_verifier.py to GenLayer Studio.",
      },
      { property: "og:title", content: "Agent Intent Verifier — GenLayer Intelligent Contract" },
      {
        property: "og:description",
        content:
          "Contract-only repository. No frontend. Deploy the contract file in contracts/ to GenLayer Studio.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

function Index() {
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center px-6 text-center">
      <p className="font-mono text-sm uppercase tracking-[0.2em] text-muted-foreground">
        Contract-only repository
      </p>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight text-foreground">
        Agent Intent Verifier
      </h1>
      <p className="mt-4 text-base leading-relaxed text-muted-foreground">
        This repository ships the GenLayer Intelligent Contract only — there is no frontend. Deploy{" "}
        <span className="font-mono text-foreground">contracts/agent_intent_verifier.py</span> to
        GenLayer Studio and call its public methods from there.
      </p>
      <p className="mt-6 text-sm text-muted-foreground">
        See <span className="font-mono text-foreground">README.md</span> for usage,{" "}
        <span className="font-mono text-foreground">examples/scenarios.json</span> for ready-to-send
        calls, and <span className="font-mono text-foreground">docs/DESIGN.md</span> for the design.
      </p>
    </main>
  );
}
