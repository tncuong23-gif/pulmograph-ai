import { useEffect, useRef } from "react";
type Tool = {
  name: string;
  description: string;
  title: string;
  inputSchema: object;
  annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
  execute: (input: unknown) => unknown | Promise<unknown>;
};
type ModelDocument = Document & {
  modelContext?: {
    registerTool: (
      tool: Tool,
      options: { signal: AbortSignal },
    ) => void | Promise<void>;
  };
};
export function useWebMcp(setDraft: (draft: string) => void) {
  const action = useRef(setDraft);
  action.current = setDraft;
  useEffect(() => {
    const context = (document as ModelDocument).modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const tool: Tool = {
      name: "stage_medical_question",
      title: "Soạn câu hỏi y tế",
      description:
        "Điền câu hỏi vào ô soạn thảo hiện tại. Không gửi câu hỏi hoặc tệp. Người dùng xem lại và bấm Gửi.",
      inputSchema: {
        type: "object",
        properties: {
          question: { type: "string", minLength: 1, maxLength: 10000 },
        },
        required: ["question"],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      async execute(input) {
        if (
          typeof input !== "object" ||
          input === null ||
          !("question" in input) ||
          typeof input.question !== "string" ||
          !input.question.trim() ||
          input.question.length > 10000 ||
          Object.keys(input).some((key) => key !== "question")
        )
          throw new Error("Câu hỏi phải có từ 1 đến 10.000 ký tự.");
        action.current(input.question);
        await new Promise<void>((resolve) =>
          requestAnimationFrame(() => resolve()),
        );
        return { status: "draft_ready", sent: false };
      },
    };
    try {
      void Promise.resolve(
        context.registerTool(tool, { signal: lifecycle.signal }),
      ).catch(() => {});
    } catch {
      /* Optional enhancement; unsupported hosts keep normal UI. */
    }
    return () => lifecycle.abort();
  }, []);
}
