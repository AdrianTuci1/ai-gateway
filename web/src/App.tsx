import { Navigate, Route, Routes } from "react-router-dom";

import { getToken } from "./api";
import { Audit } from "./pages/Audit";
import { Claim } from "./pages/Claim";
import { Grants } from "./pages/Grants";
import { GrantForm } from "./pages/GrantForm";
import { GroupDetail } from "./pages/GroupDetail";
import { GroupForm } from "./pages/GroupForm";
import { GroupResources } from "./pages/GroupResources";
import { Groups } from "./pages/Groups";
import { Identities } from "./pages/Identities";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { ResourceDetail } from "./pages/ResourceDetail";
import { ResourceForm } from "./pages/ResourceForm";
import { Resources } from "./pages/Resources";
import { Signup } from "./pages/Signup";
import { SignupReview } from "./pages/SignupReview";
import { TraceDetail } from "./pages/TraceDetail";
import { Tracing } from "./pages/Tracing";
import { useState } from "react";

export function App() {
  const [token, setToken] = useState(getToken());
  const [authView, setAuthView] = useState<"login" | "signup">("login");

  if (!token) {
    return (
      <Routes>
        <Route path="/claim/:token" element={<Claim />} />
        <Route
          path="*"
          element={
            authView === "login" ? (
              <Login
                onDone={() => setToken(getToken())}
                onSignup={() => setAuthView("signup")}
              />
            ) : (
              <Signup onBack={() => setAuthView("login")} />
            )
          }
        />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<Overview />} />
      <Route path="/claim/:token" element={<Claim />} />
      <Route path="/groups" element={<Groups />} />
      <Route path="/groups/new" element={<GroupForm />} />
      <Route path="/groups/:id" element={<GroupDetail />} />
      <Route path="/groups/:id/edit" element={<GroupForm />} />
      <Route path="/groups/:id/resources" element={<GroupResources />} />
      <Route path="/resources" element={<Resources />} />
      <Route path="/resources/new" element={<ResourceForm />} />
      <Route path="/resources/:type/:id" element={<ResourceDetail />} />
      <Route path="/resources/:type/:id/edit" element={<ResourceForm />} />
      <Route path="/resources/agent/:id/grants/new" element={<GrantForm />} />
      <Route path="/resources/agent/:id/grants/:serviceId" element={<GrantForm />} />
      <Route path="/identities" element={<Identities />} />
      <Route path="/identities/requests/:id" element={<SignupReview />} />
      <Route path="/grants" element={<Grants />} />
      <Route path="/tracing" element={<Tracing />} />
      <Route path="/tracing/:traceId" element={<TraceDetail />} />
      <Route path="/audit" element={<Audit />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
