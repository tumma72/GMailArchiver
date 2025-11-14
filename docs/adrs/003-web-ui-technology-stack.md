# ADR-003: Web UI Technology Stack (Svelte 5 + FastAPI + Tailwind)

**Status:** Accepted
**Date:** 2025-11-14
**Deciders:** Project Team
**Technical Story:** Enable non-technical users to search and browse archived emails via web interface

---

## Context

Gmail Archiver currently requires:
1. Python knowledge for installation (pip, venv)
2. Command-line proficiency
3. Technical understanding of mbox files

This creates a significant barrier for non-technical users. A web UI would:
- Lower barrier to entry
- Provide intuitive search and browse experience
- Enable mass adoption beyond developers
- Modernize the user experience

### Requirements

**Functional:**
- Search archived emails (full-text and metadata)
- Browse email list with virtualization (100k+ messages)
- View individual emails with HTML rendering
- Download attachments
- Export search results
- OAuth2 authentication flow (browser-based)

**Non-Functional:**
- **Local-first:** Runs on user's machine (127.0.0.1)
- **Secure:** No XSS vulnerabilities (HTML email rendering)
- **Fast:** < 100ms page loads, < 200ms search results
- **Mobile-responsive:** Works on tablets and phones
- **No runtime dependencies:** Should not require Node.js at runtime
- **Easy to bundle:** Packaged with Python wheel

### Technology Stack Options Considered

Several combinations of frontend + backend + styling were evaluated.

---

## Decision

We will use:

**Frontend:**
- **Svelte 5** - Reactive UI framework
- **SvelteKit** - Full-stack framework (routing, SSR optional)
- **TypeScript** - Type safety

**Backend:**
- **FastAPI** - Modern Python web framework
- **Uvicorn** - ASGI server

**Styling:**
- **Tailwind CSS** - Utility-first CSS framework
- **shadcn-svelte** - Pre-built accessible components

**Build & Distribution:**
- Build frontend to static assets at **build time** (no Node.js at runtime)
- Bundle static assets with Python wheel
- Serve via FastAPI's StaticFiles middleware

---

## Consequences

### Positive

#### Frontend (Svelte 5)

1. **Performance**
   - Compiles to vanilla JavaScript (no virtual DOM overhead)
   - Smallest bundle sizes (typically 50-70% smaller than React)
   - < 100ms page loads
   - Excellent lighthouse scores

2. **Developer Experience**
   - Less boilerplate than React/Vue
   - Intuitive reactivity (`$:` syntax)
   - Svelte 5 introduces "runes" (modern reactivity)
   - Excellent documentation

3. **Build Output**
   - Compiles to optimized static files
   - No runtime library (unlike React)
   - Easy to serve from Python

4. **SvelteKit Benefits**
   - File-based routing (`src/routes/+page.svelte`)
   - Optional SSR (can disable for pure SPA)
   - Built-in form handling
   - Zero-config Vite integration

#### Backend (FastAPI)

1. **Modern Python**
   - Async/await native support
   - Type hints and validation (Pydantic)
   - Auto-generated OpenAPI docs
   - WebSocket support (real-time progress)

2. **Performance**
   - One of the fastest Python frameworks
   - Comparable to Node.js in benchmarks
   - Efficient async I/O

3. **Integration**
   - Seamless integration with existing codebase
   - Reuse existing database layer (SQLite)
   - Reuse existing auth logic (OAuth2)
   - Same Python dependencies

4. **Developer Experience**
   - Excellent type hints and IDE support
   - Automatic validation
   - Easy testing
   - Active community

#### Styling (Tailwind + shadcn-svelte)

1. **Tailwind CSS**
   - Utility-first approach (rapid development)
   - Small production bundle (PurgeCSS)
   - Consistent design system
   - Mobile-first responsive design

2. **shadcn-svelte**
   - Pre-built accessible components
   - Customizable (copy/paste, not npm package)
   - Beautiful default styling
   - Reduced development time

3. **Dark Mode**
   - Built-in Tailwind dark mode support
   - User preference detection
   - Easy toggle implementation

### Negative

1. **Build Complexity**
   - Requires Node.js at **build time** (not runtime)
   - `package.json` and `package-lock.json` to maintain
   - More complex CI/CD pipeline
   - Two language ecosystems (Python + JavaScript)

2. **Learning Curve**
   - Svelte 5 is relatively new (Nov 2024)
   - Team must learn Svelte (if not familiar)
   - Runes are a paradigm shift from Svelte 4

3. **Ecosystem Maturity**
   - Svelte ecosystem smaller than React
   - Fewer third-party libraries
   - Some packages may need adaptation

4. **Bundle with Python Wheel**
   - Must build frontend first, then package
   - Increases wheel size (~5-10MB)
   - More complex release process

---

## Alternatives Considered

### Alternative 1: React + Next.js + Material-UI

**Pros:**
- Largest ecosystem and community
- Most third-party libraries
- Mature tooling
- Familiar to most developers

**Cons:**
- **Larger bundle sizes** (React + ReactDOM = ~140KB min+gzip)
- More boilerplate (JSX, hooks, state management)
- Slower performance vs Svelte
- Next.js is overkill for our needs (complex SSR setup)

**Verdict:** Rejected - Performance and bundle size concerns

---

### Alternative 2: Vue 3 + Nuxt + Vuetify

**Pros:**
- Good balance between React and Svelte
- Mature ecosystem
- Excellent documentation
- Component library (Vuetify) is feature-rich

**Cons:**
- Larger bundles than Svelte
- Vuetify is heavy (~300KB min+gzip)
- Nuxt adds complexity
- Options API vs Composition API confusion

**Verdict:** Rejected - Svelte is lighter and simpler

---

### Alternative 3: Alpine.js + HTMX + Tailwind

**Pros:**
- Minimal JavaScript
- Server-side rendering friendly
- Extremely lightweight
- No build step needed

**Cons:**
- **Poor for complex SPAs** (not designed for heavy client-side logic)
- Limited component ecosystem
- Harder to manage complex state
- Virtualization for large lists is difficult

**Verdict:** Rejected - Not suitable for complex email viewer

---

### Alternative 4: Vanilla JavaScript + Tailwind

**Pros:**
- Zero framework overhead
- Complete control
- Smallest possible bundle
- No build step

**Cons:**
- **High development time** (manual reactivity, routing, state)
- Hard to maintain
- No component model
- Poor developer experience

**Verdict:** Rejected - Not worth the development effort

---

### Alternative 5: Django Templates (Server-Side Rendering)

**Pros:**
- Pure Python (no JavaScript build)
- Simple deployment
- Traditional MPA approach

**Cons:**
- **Poor UX** for search (full page reloads)
- No real-time updates
- Hard to implement virtualization
- Feels dated compared to SPAs

**Verdict:** Rejected - User experience is subpar

---

### Alternative 6: Electron (Desktop App)

**Pros:**
- Native desktop app feel
- No browser required
- Can bundle everything

**Cons:**
- **Huge bundle size** (~100MB+ with Chromium)
- Overkill for our use case
- More complex distribution
- Another technology to learn

**Verdict:** Rejected - Web UI is simpler and lighter

---

## Implementation Details

### Directory Structure

```
src/gmailarchiver/
├── web/
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── api.py              # FastAPI app
│   │   ├── routes/
│   │   │   ├── auth.py         # OAuth2 flow
│   │   │   ├── search.py       # Search endpoints
│   │   │   ├── messages.py     # Message CRUD
│   │   │   └── archives.py     # Archive management
│   │   └── websocket.py        # Real-time updates
│   │
│   ├── frontend/               # SvelteKit app
│   │   ├── src/
│   │   │   ├── routes/
│   │   │   │   ├── +page.svelte           # Search page
│   │   │   │   ├── +layout.svelte         # App shell
│   │   │   │   ├── message/
│   │   │   │   │   └── [id]/
│   │   │   │   │       └── +page.svelte   # Email viewer
│   │   │   │   └── settings/
│   │   │   │       └── +page.svelte       # Settings
│   │   │   ├── lib/
│   │   │   │   ├── components/
│   │   │   │   │   ├── EmailList.svelte
│   │   │   │   │   ├── EmailViewer.svelte
│   │   │   │   │   ├── SearchBar.svelte
│   │   │   │   │   └── ui/              # shadcn-svelte components
│   │   │   │   └── api.ts               # API client
│   │   │   └── app.html
│   │   ├── static/             # Static assets
│   │   │   └── favicon.png
│   │   ├── svelte.config.js
│   │   ├── vite.config.ts
│   │   ├── tailwind.config.js
│   │   ├── package.json
│   │   └── tsconfig.json
│   │
│   └── static/                 # Built assets (post-build)
│       ├── _app/
│       │   ├── immutable/
│       │   └── version.json
│       └── index.html
```

### Build Process

```bash
# Development
cd src/gmailarchiver/web/frontend
npm install
npm run dev  # Vite dev server on :5173

# Production build
npm run build  # Outputs to ../static/

# Python package includes static/ directory
uv build  # Builds wheel with bundled frontend
```

### FastAPI Application

```python
# src/gmailarchiver/web/backend/api.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()

# API routes
app.include_router(auth.router, prefix="/api/auth")
app.include_router(search.router, prefix="/api/search")
app.include_router(messages.router, prefix="/api/messages")

# WebSocket for real-time updates
app.include_router(websocket.router, prefix="/ws")

# Serve static frontend (built Svelte app)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

# API fallback to SPA (for client-side routing)
@app.get("/{path:path}")
async def catch_all(path: str):
    # Try to serve file, fallback to index.html
    file_path = Path("static") / path
    if file_path.exists():
        return FileResponse(file_path)
    return FileResponse("static/index.html")
```

### Example Svelte Component

```svelte
<!-- src/gmailarchiver/web/frontend/src/lib/components/SearchBar.svelte -->
<script lang="ts">
  import { searchMessages } from '$lib/api';

  let query = $state('');
  let results = $state([]);
  let loading = $state(false);

  async function handleSearch() {
    loading = true;
    try {
      results = await searchMessages(query);
    } finally {
      loading = false;
    }
  }
</script>

<div class="flex gap-2">
  <input
    type="text"
    bind:value={query}
    placeholder="Search emails..."
    class="flex-1 px-4 py-2 border rounded-lg"
    onkeypress={(e) => e.key === 'Enter' && handleSearch()}
  />
  <button
    onclick={handleSearch}
    disabled={loading}
    class="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
  >
    {loading ? 'Searching...' : 'Search'}
  </button>
</div>

{#if results.length > 0}
  <div class="mt-4 space-y-2">
    {#each results as message}
      <div class="p-4 border rounded-lg hover:bg-gray-50">
        <h3 class="font-semibold">{message.subject}</h3>
        <p class="text-sm text-gray-600">{message.from_addr}</p>
        <p class="text-sm mt-2">{@html message.snippet}</p>
      </div>
    {/each}
  </div>
{/if}
```

---

## Security Considerations

### HTML Email Rendering

**Risk:** XSS attacks via malicious HTML emails

**Mitigation:**
```svelte
<!-- Safe iframe rendering -->
<iframe
  srcdoc={emailHtml}
  sandbox="allow-same-origin"
  csp="default-src 'none'; style-src 'unsafe-inline'; img-src data: https:"
  class="w-full h-full border-0"
  title="Email content"
/>
```

**Layers of protection:**
1. `sandbox="allow-same-origin"` - No scripts, forms, popups
2. CSP headers - No external resources
3. iframe isolation - Can't access parent window

### API Security

```python
# CORS (local-only by default)
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF protection
from fastapi_csrf_protect import CsrfProtect

@app.post("/api/delete")
async def delete_message(message_id: str, csrf_protect: CsrfProtect = Depends()):
    await csrf_protect.validate_csrf()
    # ... deletion logic
```

### Authentication (Future)

For remote access, add optional password protection:
```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    # Check against configured password
    if not verify_password(credentials.password):
        raise HTTPException(status_code=401)
    return credentials.username
```

---

## Performance Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| Page load (initial) | < 100ms | Instant feel |
| Search results | < 200ms | Responsive UX |
| Email viewer load | < 500ms | Includes HTML parsing |
| Bundle size (JS) | < 500KB | Fast downloads |
| Bundle size (CSS) | < 50KB | Tailwind purged |

### Optimization Strategies

1. **Code Splitting**
   ```javascript
   // Lazy load email viewer
   const EmailViewer = () => import('./EmailViewer.svelte');
   ```

2. **Virtual Scrolling**
   - Use `svelte-virtual` for large email lists
   - Render only visible items (100-200 at a time)

3. **Image Lazy Loading**
   ```svelte
   <img src={url} loading="lazy" alt="Attachment" />
   ```

4. **Caching**
   ```python
   from fastapi_cache import FastAPICache
   from fastapi_cache.backends.inmemory import InMemoryBackend

   @app.on_event("startup")
   async def startup():
       FastAPICache.init(InMemoryBackend())

   @app.get("/api/messages/{id}")
   @cache(expire=3600)  # Cache for 1 hour
   async def get_message(id: str):
       return fetch_message(id)
   ```

---

## Development Workflow

### Local Development

```bash
# Terminal 1: Start FastAPI backend
uv run uvicorn gmailarchiver.web.backend.api:app --reload

# Terminal 2: Start Vite dev server (Svelte)
cd src/gmailarchiver/web/frontend
npm run dev

# Browser: http://localhost:5173
# Proxies API requests to :8000
```

### Production Build

```bash
# 1. Build frontend
cd src/gmailarchiver/web/frontend
npm run build  # Outputs to ../static/

# 2. Build Python wheel (includes static/)
cd ../../../..
uv build

# 3. Install and run
pip install dist/gmailarchiver-*.whl
gmailarchiver serve  # Opens http://localhost:8080
```

---

## Related Decisions

- [ADR-002: SQLite FTS5 for Search](002-sqlite-fts5-search.md) - Backend search implementation
- [ADR-005: Distribution Strategy](005-distribution-strategy.md) - How web UI is packaged

---

## References

- Svelte 5 Docs: https://svelte.dev/docs/svelte/overview
- SvelteKit: https://kit.svelte.dev/
- FastAPI: https://fastapi.tiangolo.com/
- Tailwind CSS: https://tailwindcss.com/
- shadcn-svelte: https://www.shadcn-svelte.com/
- Svelte Virtual: https://github.com/Cifrazia/svelte-virtual

---

**Last Updated:** 2025-11-14
