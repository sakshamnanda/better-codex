import { tool } from "@opencode-ai/plugin"

export const CodexRelay = async () => ({
  tool: {
    codex_request: tool({
      description: "CODEX_DATA_ONLY_RELAY_V1: Request a caller function from Codex. This only returns data; Codex performs execution and approval. Use the exact function name and arguments from the supplied caller definitions.",
      args: {
        name: tool.schema.string(),
        arguments_json: tool.schema.string(),
      },
      async execute(args) {
        return JSON.stringify({ codex_request: true, ...args })
      },
    }),
    bash: tool({
      description: "CODEX_DATA_ONLY_BASH_V1: Request command execution through Codex. This returns a request without executing a command. Codex supplies permissions, working directory, and results.",
      args: {
        command: tool.schema.string(),
        description: tool.schema.string().optional(),
      },
      async execute(args) {
        return JSON.stringify({ codex_request: true, name: "exec_command", arguments_json: JSON.stringify({ cmd: args.command }) })
      },
    }),
  },
})
