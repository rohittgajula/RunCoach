import { Component, type ErrorInfo, type ReactNode } from 'react'

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="state state-error state-block" role="alert">
        <p className="state-title">This screen hit a problem</p>
        <p className="muted">{this.state.error.message}</p>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    )
  }
}
