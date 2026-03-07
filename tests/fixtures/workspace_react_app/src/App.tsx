import { Routes, Route } from 'react-router-dom';
import { DashboardPage } from './routes/DashboardPage';

export function App(): JSX.Element {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
    </Routes>
  );
}
