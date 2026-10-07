import { Link } from 'react-router-dom';
import { API_MODE } from '@/api/http';

export function Footer() {
  return (
    <footer className="footer">
      <span className="t-mono" style={{ letterSpacing: '0.24em' }}>
        COGNIS
      </span>
      <span>Company intelligence, built from evidence</span>
      <span>Builderr Signalpost Hackathon</span>
      <span className="t-mono">v0.1.0{API_MODE === 'mock' ? ' · demo data' : ''}</span>
      <span className="spacer" />
      <Link to="/about">About & data limitations</Link>
      <Link to="/settings">Status</Link>
    </footer>
  );
}
