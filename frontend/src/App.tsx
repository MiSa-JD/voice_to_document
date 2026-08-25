import { createBrowserRouter, RouterProvider } from 'react-router-dom';

import { DashboardPage } from './pages/DashboardPage';
import { HealthPage } from './pages/HealthPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RecordingDetailPage } from './pages/RecordingDetailPage';

const router = createBrowserRouter([
  { path: '/', element: <DashboardPage /> },
  { path: '/recordings/:id', element: <RecordingDetailPage /> },
  { path: '/service-status', element: <HealthPage /> },
  { path: '*', element: <NotFoundPage /> },
]);

export function App() {
  return <RouterProvider router={router} />;
}
