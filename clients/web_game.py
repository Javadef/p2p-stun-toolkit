#!/usr/bin/env python3
"""
P2P Game Web Interface
Beautiful web UI for P2P Tic-Tac-Toe using WebSockets
"""

import asyncio
import json
import os
from aiohttp import web
from mesh_network import MeshNetwork
from typing import Optional, Set
from dataclasses import dataclass, asdict


@dataclass
class GameState:
    board: list
    players: list
    current_turn: str
    my_symbol: str
    opponent_symbol: str
    game_started: bool
    game_over: bool
    winner: Optional[str]
    is_host: bool
    my_ip: str


class WebGame:
    def __init__(self):
        self.mesh: Optional[MeshNetwork] = None
        self.websockets: Set[web.WebSocketResponse] = set()
        self.game_state: Optional[GameState] = None
        self.pending_invite_from: Optional[str] = None
        self.host_ip: Optional[str] = None
        
    def reset_game(self):
        """Reset the game state"""
        self.game_state = GameState(
            board=[['' for _ in range(3)] for _ in range(3)],
            players=[],
            current_turn='',
            my_symbol='',
            opponent_symbol='',
            game_started=False,
            game_over=False,
            winner=None,
            is_host=False,
            my_ip=self.mesh.virtual_ip if self.mesh else ''
        )
        
    async def broadcast_to_web(self, msg_type: str, data: dict):
        """Send message to all connected web clients"""
        message = json.dumps({'type': msg_type, **data})
        dead_sockets = set()
        for ws in self.websockets:
            try:
                await ws.send_str(message)
            except:
                dead_sockets.add(ws)
        self.websockets -= dead_sockets
        
    def handle_mesh_message(self, from_ip: str, data):
        """Handle messages from mesh network"""
        print(f"[MESH] From {from_ip}: {data}")
        
        if not isinstance(data, dict):
            return
            
        msg_type = data.get('msg_type')
        
        if msg_type == 'game_invite':
            self.pending_invite_from = from_ip
            self.host_ip = from_ip
            asyncio.create_task(self.broadcast_to_web('invite', {
                'from': from_ip,
                'game': data.get('game_type')
            }))
            
        elif msg_type == 'game_accept':
            # Someone accepted our invite
            if self.game_state and self.game_state.is_host:
                self.game_state.players.append(from_ip)
                self.game_state.game_started = True
                self.game_state.current_turn = self.mesh.virtual_ip  # Host goes first
                asyncio.create_task(self.broadcast_to_web('game_state', {'state': asdict(self.game_state)}))
                # Send state to opponent
                asyncio.create_task(self.send_game_state())
                
        elif msg_type == 'game_state':
            # Received state from host
            state_data = data.get('state', {})
            if self.game_state:
                self.game_state.board = state_data.get('board', self.game_state.board)
                self.game_state.current_turn = state_data.get('current_turn', '')
                self.game_state.game_started = state_data.get('game_started', False)
                self.game_state.game_over = state_data.get('game_over', False)
                self.game_state.winner = state_data.get('winner')
                asyncio.create_task(self.broadcast_to_web('game_state', {'state': asdict(self.game_state)}))
                
        elif msg_type == 'game_move':
            # Opponent made a move
            move = data.get('move', {})
            row, col = move.get('row'), move.get('col')
            if self.game_state and row is not None and col is not None:
                symbol = 'O' if self.game_state.is_host else 'X'
                self.game_state.board[row][col] = symbol
                self.game_state.current_turn = self.mesh.virtual_ip
                
                # Check for winner
                winner = self.check_winner()
                if winner:
                    self.game_state.game_over = True
                    self.game_state.winner = winner
                elif self.is_draw():
                    self.game_state.game_over = True
                    self.game_state.winner = 'draw'
                    
                asyncio.create_task(self.broadcast_to_web('game_state', {'state': asdict(self.game_state)}))
                if self.game_state.is_host:
                    asyncio.create_task(self.send_game_state())
                    
    async def send_game_state(self):
        """Send game state to all mesh peers"""
        if self.mesh and self.game_state:
            await self.mesh.broadcast({
                'game_type': 'tictactoe',
                'msg_type': 'game_state',
                'state': {
                    'board': self.game_state.board,
                    'current_turn': self.game_state.current_turn,
                    'game_started': self.game_state.game_started,
                    'game_over': self.game_state.game_over,
                    'winner': self.game_state.winner
                }
            })
            
    def check_winner(self) -> Optional[str]:
        """Check if there's a winner"""
        board = self.game_state.board
        lines = []
        # Rows and columns
        for i in range(3):
            lines.append([board[i][0], board[i][1], board[i][2]])
            lines.append([board[0][i], board[1][i], board[2][i]])
        # Diagonals
        lines.append([board[0][0], board[1][1], board[2][2]])
        lines.append([board[0][2], board[1][1], board[2][0]])
        
        for line in lines:
            if line[0] and line[0] == line[1] == line[2]:
                return line[0]
        return None
        
    def is_draw(self) -> bool:
        """Check if game is a draw"""
        return all(self.game_state.board[i][j] for i in range(3) for j in range(3))


game = WebGame()


async def websocket_handler(request):
    """Handle WebSocket connections from web UI"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    game.websockets.add(ws)
    
    # Send initial state
    peers = [{'ip': p.virtual_ip, 'external': f"{p.external_ip}:{p.external_port}"} 
             for p in game.mesh.get_peers()] if game.mesh else []
    await ws.send_str(json.dumps({
        'type': 'init',
        'connected': game.mesh is not None,
        'my_ip': game.mesh.virtual_ip if game.mesh else '',
        'external': f"{game.mesh.external_ip}:{game.mesh.external_port}" if game.mesh else '',
        'peers': peers,
        'state': asdict(game.game_state) if game.game_state else None
    }))
    
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                await handle_ws_message(ws, data)
    finally:
        game.websockets.discard(ws)
        
    return ws


async def handle_ws_message(ws: web.WebSocketResponse, data: dict):
    """Handle messages from web UI"""
    action = data.get('action')
    
    if action == 'connect':
        # Connect to mesh network
        network = data.get('network', 'game-network')
        secret = data.get('secret', 'game-secret-123')
        peer = data.get('peer')  # Optional: ip:port to connect to
        
        game.mesh = MeshNetwork(network, secret, 0)
        game.mesh.on_message = game.handle_mesh_message
        game.mesh.on_peer_connected = lambda p: asyncio.create_task(
            game.broadcast_to_web('peer_connected', {'ip': p.virtual_ip, 'external': f"{p.external_ip}:{p.external_port}"})
        )
        game.mesh.on_peer_disconnected = lambda p: asyncio.create_task(
            game.broadcast_to_web('peer_disconnected', {'ip': p.virtual_ip})
        )
        
        await game.mesh.start()
        game.reset_game()
        
        if peer:
            ip, port = peer.split(':')
            await game.mesh.connect_to_peer(ip, int(port))
            await asyncio.sleep(2)
            
        peers = [{'ip': p.virtual_ip, 'external': f"{p.external_ip}:{p.external_port}"} 
                 for p in game.mesh.get_peers()]
        await ws.send_str(json.dumps({
            'type': 'connected',
            'my_ip': game.mesh.virtual_ip,
            'external': f"{game.mesh.external_ip}:{game.mesh.external_port}",
            'peers': peers
        }))
        
    elif action == 'start_game':
        # Start a new game as host
        if game.mesh:
            game.reset_game()
            game.game_state.is_host = True
            game.game_state.my_symbol = 'X'
            game.game_state.opponent_symbol = 'O'
            game.game_state.players = [game.mesh.virtual_ip]
            game.game_state.my_ip = game.mesh.virtual_ip
            
            await game.mesh.broadcast({
                'game_type': 'tictactoe',
                'msg_type': 'game_invite',
                'host': game.mesh.virtual_ip
            })
            await game.broadcast_to_web('waiting', {'message': 'Waiting for opponent...'})
            
    elif action == 'accept_invite':
        # Accept game invitation
        if game.mesh and game.pending_invite_from:
            game.reset_game()
            game.game_state.is_host = False
            game.game_state.my_symbol = 'O'
            game.game_state.opponent_symbol = 'X'
            game.game_state.players = [game.pending_invite_from, game.mesh.virtual_ip]
            game.game_state.game_started = True
            game.game_state.current_turn = game.pending_invite_from  # Host goes first
            game.game_state.my_ip = game.mesh.virtual_ip
            game.host_ip = game.pending_invite_from
            
            await game.mesh.send(game.pending_invite_from, {
                'game_type': 'tictactoe',
                'msg_type': 'game_accept',
                'player': game.mesh.virtual_ip
            })
            game.pending_invite_from = None
            await game.broadcast_to_web('game_state', {'state': asdict(game.game_state)})
            
    elif action == 'move':
        # Make a move
        row, col = data.get('row'), data.get('col')
        if game.mesh and game.game_state and not game.game_state.game_over:
            if game.game_state.current_turn == game.mesh.virtual_ip:
                if game.game_state.board[row][col] == '':
                    game.game_state.board[row][col] = game.game_state.my_symbol
                    
                    # Send move to opponent
                    await game.mesh.broadcast({
                        'game_type': 'tictactoe',
                        'msg_type': 'game_move',
                        'player': game.mesh.virtual_ip,
                        'move': {'row': row, 'col': col}
                    })
                    
                    # Check winner
                    winner = game.check_winner()
                    if winner:
                        game.game_state.game_over = True
                        game.game_state.winner = winner
                    elif game.is_draw():
                        game.game_state.game_over = True
                        game.game_state.winner = 'draw'
                    else:
                        # Switch turn
                        peers = game.mesh.get_peers()
                        if peers:
                            game.game_state.current_turn = peers[0].virtual_ip
                            
                    await game.broadcast_to_web('game_state', {'state': asdict(game.game_state)})
                    if game.game_state.is_host:
                        await game.send_game_state()


async def index_handler(request):
    """Serve the main HTML page"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), 'web_game.html')
    return web.FileResponse(html_path)


async def init_app():
    import os
    static_path = os.path.join(os.path.dirname(__file__), 'static')
    app = web.Application()
    app.router.add_get('/', index_handler)
    app.router.add_get('/ws', websocket_handler)
    if os.path.exists(static_path):
        app.router.add_static('/static/', static_path)
    return app


if __name__ == '__main__':
    print("🎮 Starting P2P Game Web Server...")
    print("📱 Open http://localhost:8080 in your browser")
    web.run_app(init_app(), host='0.0.0.0', port=8080)
