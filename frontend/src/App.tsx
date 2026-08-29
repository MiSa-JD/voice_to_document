import { createBrowserRouter, RouterProvider } from 'react-router-dom';

import { DashboardPage } from './pages/DashboardPage';
import { HealthPage } from './pages/HealthPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RecordingDetailPage } from './pages/RecordingDetailPage';
import { SpeakerReviewPage } from './pages/SpeakerReviewPage';

const router = createBrowserRouter([
  { path: '/', element: <DashboardPage /> },
  { path: '/recordings/:id', element: <RecordingDetailPage /> },
  { path: '/recordings/:id/speakers', element: <SpeakerReviewPage /> },
  { path: '/service-status', element: <HealthPage /> },
  { path: '*', element: <NotFoundPage /> },
]);

export function App() {
  return <RouterProvider router={router} />;
}
