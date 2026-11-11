/** Same-origin JSON helper. Flask session cookies ride along automatically. */

class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface ApiOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Defaults to GET without a body and POST with one. */
  method?: "GET" | "POST" | "PUT" | "DELETE";
}

export async function api<T>(
  path: string,
  body?: unknown,
  { signal, timeoutMs = 30_000, method }: ApiOptions = {},
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const forwardAbort = () => controller.abort();

  if (signal) {
    if (signal.aborted) {
      controller.abort();
    } else {
      signal.addEventListener("abort", forwardAbort, { once: true });
    }
  }

  try {
    const response = await fetch(path, {
      method: method ?? (body === undefined ? "GET" : "POST"),
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const json = (await response.json().catch(() => ({}))) as {
      error?: string;
      login_url?: string;
    };

    if (response.status === 401 && json.login_url) {
      // The login session expired: bounce to the sign-in page.
      window.location.assign(json.login_url);
      throw new ApiError("Please sign in again.", 401);
    }

    if (!response.ok) {
      throw new ApiError(
        json.error ?? `Request failed (${response.status})`,
        response.status,
      );
    }

    return json as T;
  } catch (error) {
    if (timedOut) {
      throw new ApiError(
        "Request timed out. The backend may still be loading. Please try again.",
        0,
      );
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener("abort", forwardAbort);
  }
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
