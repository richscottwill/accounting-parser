import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

/**
 * EngagementLookup — temporary UI for P1.5.
 *
 * Full engagement listing requires a backend route we haven't
 * shipped (no GET /engagements). That lands in P2 alongside the
 * client+engagement CRUD routes. For now this form lets the
 * operator enter an engagement id and routes to the engagement
 * detail page. Playwright tests use this as the entry point.
 */
export function EngagementLookup() {
  const [id, setId] = useState("");
  const navigate = useNavigate();

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (id.trim()) navigate(`/engagement/${id.trim()}`);
  }

  return (
    <main className="engagement-lookup">
      <h1>Open engagement</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Engagement id (UUID)
          <input
            type="text"
            required
            value={id}
            onChange={(e) => setId(e.target.value)}
            data-testid="engagement-id-input"
          />
        </label>
        <button type="submit" data-testid="engagement-open">
          Open
        </button>
      </form>
    </main>
  );
}
