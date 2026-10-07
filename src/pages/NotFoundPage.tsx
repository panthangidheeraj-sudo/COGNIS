import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/common/EmptyState';

export default function NotFoundPage() {
  return (
    <div className="page">
      <EmptyState
        center
        title="This page does not exist"
        text="The link may be outdated, or the research artifact may have been archived."
        action={
          <>
            <Link to="/" className="btn">
              Go home
            </Link>
            <Link to="/library" className="btn btn--ghost">
              Open library
            </Link>
          </>
        }
      />
    </div>
  );
}
