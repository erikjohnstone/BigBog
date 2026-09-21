import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

import { ErrorState } from '../design-system/states';

interface Props {
  children: ReactNode;
  /** Names the surface in the fallback so a crashed panel is identifiable. */
  scope?: string;
  compact?: boolean;
}

interface State {
  error: Error | null;
}

/**
 * Per-route and per-panel boundary. A panel that throws must never take the
 * shell down with it: the panel shows its own error and the rest keeps
 * working.
 */
export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface in the console for diagnosis; there is no telemetry sink.
    console.error(`[bactalk] ${this.props.scope ?? 'view'} crashed`, error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <ErrorState
          compact={this.props.compact}
          title={`${this.props.scope ?? 'This view'} hit an unexpected error`}
          error={this.state.error}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
