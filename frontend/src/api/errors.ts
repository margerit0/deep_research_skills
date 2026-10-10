export class ApiError extends Error {
  status: number
  constructor(status: number) {
    super(`LangGraph HTTP ${status}`)
    this.status = status
  }
}
