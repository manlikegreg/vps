# 🖥️ Web Terminal Project

A full-stack web terminal application with authentication, built with FastAPI backend and React TypeScript frontend.

## 🌟 Features

- **Secure Authentication**: JWT-based login system
- **Real-time Terminal**: WebSocket-powered terminal with live command execution
- **Command Sandboxing**: Safe command execution with whitelisted commands
- **Modern UI**: Hacker-style terminal interface with xterm.js
- **Command History**: Navigate through previous commands with arrow keys
- **Responsive Design**: Works on desktop and mobile devices

## 🏗️ Architecture

- **Backend**: FastAPI + Python-SocketIO + Uvicorn
- **Frontend**: React + TypeScript + Vite + xterm.js
- **Deployment**: Render (Backend) + Netlify (Frontend)

## 📁 Project Structure

```
project-root/
├── backend/
│   ├── main.py                 # FastAPI application with WebSocket
│   ├── requirements.txt        # Python dependencies
│   ├── .env                   # Environment variables
│   ├── .env.example           # Environment variables template
│   ├── utils/
│   │   └── sandbox.py         # Command execution sandbox
│   └── config/
│       └── settings.py        # Application settings
├── frontend/
│   ├── src/
│   │   ├── main.tsx           # React entry point
│   │   ├── App.tsx            # Main application component
│   │   ├── components/
│   │   │   ├── Terminal.tsx   # Terminal interface with xterm.js
│   │   │   └── Login.tsx      # Authentication form
│   │   ├── hooks/
│   │   │   └── useSocket.ts   # WebSocket management hook
│   │   ├── styles/
│   │   │   └── terminal.css   # Terminal and UI styles
│   │   └── utils/
│   │       └── api.ts         # API client utilities
│   ├── index.html             # HTML template
│   ├── package.json           # Node.js dependencies
│   ├── vite.config.ts         # Vite configuration
│   └── .env.example           # Frontend environment template
├── render.yaml                # Render deployment config
└── README.md                  # This file
```

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Node.js 16+
- npm or yarn

### Backend Setup

1. **Navigate to backend directory**:
   ```bash
   cd backend
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your preferred credentials
   ```

4. **Run the backend**:
   ```bash
   # From backend directory:
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   # From vps directory:
   uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

### Frontend Setup

1. **Navigate to frontend directory**:
   ```bash
   cd frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Update VITE_API_URL to match your backend URL
   ```

4. **Run the frontend**:
   ```bash
   npm run dev
   ```

5. **Open your browser** and navigate to `http://localhost:5173/`

## 🔐 Default Credentials

- **Username**: `admin`
- **Password**: `supersecret`

> ⚠️ **Security Note**: Change these credentials in production!

## 🛠️ Available Commands

The terminal supports the following whitelisted commands:

- **File Operations**: `ls`, `cat`, `pwd`, `find`, `head`, `tail`
- **Text Processing**: `echo`, `grep`, `wc`, `sort`, `uniq`
- **System Info**: `whoami`, `date`
- **Development**: `python3`, `python`, `pip`, `pip3`, `node`, `npm`, `git`
- **Network**: `curl`, `wget`
- **Special**: `clear`, `help`

## 🌐 Deployment

### Backend Deployment (Render)

1. **Connect your GitHub repository** to Render
2. **Create a new Web Service** with these settings:
   - **Build Command**: `pip install -r backend/requirements.txt`
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Environment Variables**: Set from `.env.example`

3. **Deploy** and note your backend URL

### Frontend Deployment (Netlify)

1. **Build the frontend**:
   ```bash
   cd frontend
   npm run build
   ```

2. **Deploy to Netlify**:
   - Drag and drop the `dist/` folder to Netlify
   - Or connect your GitHub repository
   - **Build Command**: `npm run build`
   - **Publish Directory**: `dist`

3. **Set environment variables** in Netlify:
   - `VITE_API_URL`: Your Render backend URL

## 🔧 Configuration

### Backend Environment Variables

```env
# Admin auth (agent)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
TOKEN_TTL_SECONDS=86400

# CORS
FRONTEND_URL=http://localhost:5173

# Optional TLS pinning for Master WS (WSS)
# Set one of these to enable pinning; leave empty to disable
MASTER_CERT_SHA256=                             # sha256 fingerprint (hex, no colons)
MASTER_CA_PEM_PATH=                             # path to PEM with trusted CA/leaf

# Agent HTTP base (for master proxy features)
AGENT_HTTP_BASE=http://localhost:8000

CAMERA_ENABLED=1
```

### Frontend Environment Variables

```env
VITE_API_URL=https://your-backend.onrender.com  # Backend API URL
```

### TLS certificate pinning (Agent -> Master) [Optional]

Pin the agent to your Master Control TLS certificate to prevent MITM and imposter servers.

1) Compute the SHA256 fingerprint of the master's leaf certificate:

Windows/Python (cross‑platform):

```bash
python -c "import ssl,socket,hashlib; h='mastervpsback.onrender.com'; ctx=ssl.create_default_context(); s=socket.create_connection((h,443),timeout=10); ss=ctx.wrap_socket(s,server_hostname=h); print(hashlib.sha256(ss.getpeercert(True)).hexdigest())"
```

2) Set the value in `backend/.env`:

```env
MASTER_CERT_SHA256=<paste_hex_from_step_1>
```

Alternative: instead of fingerprint pinning, trust only a specific CA/leaf PEM:

```env
MASTER_CA_PEM_PATH=path/to/your_ca_or_leaf.pem
```

3) Restart the agent backend.

Notes:
- Pinning only applies to `wss://` URLs (ignored for `ws://`).
- If your certificate renews/changes, you must update the pin.
- If using multiple master URLs with different certs, the single fingerprint must match each (or use `MASTER_CA_PEM_PATH`).

## 🛡️ Security Features

- **JWT Authentication**: Secure token-based authentication
- **Command Whitelisting**: Only approved commands can be executed
- **Sandboxed Execution**: Commands run in a restricted directory
- **CORS Protection**: Configurable cross-origin resource sharing
- **Input Validation**: All user inputs are validated and sanitized

## 🎨 Customization

### Terminal Theme

Edit `frontend/src/styles/terminal.css` to customize:
- Colors and fonts
- Terminal appearance
- Login form styling

### Command Whitelist

Modify `backend/config/settings.py` to add/remove allowed commands:

```python
ALLOWED_COMMANDS = [
    "ls", "cat", "pwd", "echo", "whoami", "date",
    "python3", "python", "pip", "node", "npm", "git"
    # Add your commands here
]
```

## 🐛 Troubleshooting

### Common Issues

1. **WebSocket Connection Failed**:
   - Check if backend is running
   - Verify CORS settings
   - Ensure correct API URL in frontend

2. **Authentication Errors**:
   - Verify credentials in `.env`
   - Check JWT secret key configuration
   - Ensure token hasn't expired

3. **Command Execution Fails**:
   - Check if command is in whitelist
   - Verify sandbox directory permissions
   - Review backend logs for errors

4. **Uvicorn import error: `ModuleNotFoundError: No module named 'backend'`**:
   - If you run from `vps/backend`, use: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
   - If you run from `vps` root, use: `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
   - Do not use `backend.main:...` while your working directory is `vps/backend`

5. **ASGI app attribute error: `Attribute "socket_app" not found`**:
   - The FastAPI app variable is `app` in `backend/main.py`
   - Use `main:app` or `backend.main:app` in your start command
   - Update any deployment/start scripts to reference `app`

### Development Tips

- Use browser developer tools to debug WebSocket connections
- Check backend logs for detailed error messages
- Test API endpoints directly with tools like Postman

## 📝 API Documentation

### Authentication Endpoints

- `POST /login` - Authenticate user and get JWT token
- `GET /verify` - Verify JWT token validity

### WebSocket Events

- `connect` - Client connection with JWT auth
- `command` - Send command for execution
- `output` - Receive command output
- `prompt` - Receive new prompt signal

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

## 🙏 Acknowledgments

- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [xterm.js](https://xtermjs.org/) - Terminal emulator for the web
- [React](https://reactjs.org/) - JavaScript library for building UIs
- [Vite](https://vitejs.dev/) - Next generation frontend tooling

---

**Happy Terminal Hacking! 🚀**