import type { Message } from "./types";


export function parseSSELine(
    line: string,
    onToken: (token: string) => void,
    onDone: (sources: Message["sources"], tools: Message["tools"]) => void,
    _onError: (err: Error) => void,
    close: () => void
) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith(":")) return;

    const eventMatch = trimmed.match(/^event:\s*(.+)$/);
    if (eventMatch) {
        // next line will contain the data; store is not needed for simple parser
        return;
    }

    const dataMatch = trimmed.match(/^data:\s*(.+)$/);
    if (!dataMatch) return;

    try {
        const data = JSON.parse(dataMatch[1]);
        if (data.token) {
            onToken(data.token);
        }
        if (data.sources || data.tools) {
            onDone(data.sources || [], data.tools || []);
            close();
        }
    } catch {
        onToken(dataMatch[1]);
    }
}
