import type { Role } from "./types";

/** Raised when the backend (real or mock) returns a non-2xx response. */
export class ApiError extends Error {
  readonly status: number;
  readonly role: Role;
  constructor(status: number, message: string, role: Role) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.role = role;
  }

  /** True for auth/permission failures (used to show a friendly RBAC note). */
  get isForbidden(): boolean {
    return this.status === 401 || this.status === 403;
  }
}
