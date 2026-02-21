import { Component, type ReactNode } from 'react';
import { getT } from '../i18n';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/** React Error Boundary для перехвата ошибок рендеринга */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('ErrorBoundary:', error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      const t = getT();
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
          <div className="max-w-md w-full bg-white rounded-lg shadow-sm p-6 text-center">
            <h2 className="text-lg font-semibold text-red-800 mb-2">
              {t('errorBoundary.title')}
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              {t('errorBoundary.message')}
            </p>
            {this.state.error && (
              <p className="text-xs text-red-600 font-mono bg-red-50 rounded p-2 mb-4 break-words">
                {this.state.error.message}
              </p>
            )}
            <button
              onClick={this.handleReset}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
            >
              {t('errorBoundary.reload')}
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
