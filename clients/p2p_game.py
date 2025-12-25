#!/usr/bin/env python3
"""
P2P Game Framework using Mesh Network
Build multiplayer games that work through NAT!

Examples included:
- Real-time Chat
- Tic-Tac-Toe
- Drawing Canvas
"""

import asyncio
import json
import time
import random
from mesh_network import MeshNetwork
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class GameState:
    game_type: str
    players: List[str]
    current_turn: str
    data: dict
    started: bool = False
    finished: bool = False


class P2PGame:
    """Base class for P2P games"""
    
    def __init__(self, mesh: MeshNetwork):
        self.mesh = mesh
        self.game_state: Optional[GameState] = None
        self.is_host = False
        
        # Override mesh message handler
        self._original_handler = mesh.on_message
        mesh.on_message = self._handle_game_message
    
    def _handle_game_message(self, from_ip: str, data):
        """Handle incoming game messages"""
        if isinstance(data, dict) and 'game_type' in data:
            msg_type = data.get('msg_type')
            
            if msg_type == 'game_invite':
                self._on_invite(from_ip, data)
            elif msg_type == 'game_accept':
                self._on_accept(from_ip, data)
            elif msg_type == 'game_move':
                self._on_move(from_ip, data)
            elif msg_type == 'game_state':
                self._on_state_update(from_ip, data)
            elif msg_type == 'game_chat':
                print(f"\n💬 [{from_ip}]: {data.get('message')}")
        elif self._original_handler:
            self._original_handler(from_ip, data)
    
    def _on_invite(self, from_ip: str, data: dict):
        """Handle game invitation"""
        print(f"\n🎮 Game invite from {from_ip}: {data.get('game_type')}")
        print(f"   Type 'accept' to join!")
        self.pending_invite = (from_ip, data)
    
    def _on_accept(self, from_ip: str, data: dict):
        """Handle game acceptance"""
        print(f"\n✅ {from_ip} joined the game!")
        if self.game_state:
            self.game_state.players.append(from_ip)
            self.game_state.started = True
            asyncio.create_task(self._broadcast_state())
    
    def _on_move(self, from_ip: str, data: dict):
        """Handle game move - override in subclass"""
        pass
    
    def _on_state_update(self, from_ip: str, data: dict):
        """Handle state update from host"""
        if not self.is_host:
            self.game_state = GameState(**data.get('state', {}))
            self._render_game()
    
    async def _broadcast_state(self):
        """Broadcast game state to all players"""
        if self.game_state:
            await self.mesh.broadcast({
                'game_type': self.game_state.game_type,
                'msg_type': 'game_state',
                'state': self.game_state.__dict__
            })
    
    async def invite(self, game_type: str):
        """Send game invite to all peers"""
        self.is_host = True
        self.game_state = GameState(
            game_type=game_type,
            players=[self.mesh.virtual_ip],
            current_turn=self.mesh.virtual_ip,
            data={}
        )
        
        await self.mesh.broadcast({
            'game_type': game_type,
            'msg_type': 'game_invite',
            'host': self.mesh.virtual_ip
        })
        print(f"📤 Sent {game_type} invite to all peers")
    
    async def accept_invite(self):
        """Accept pending invitation"""
        if hasattr(self, 'pending_invite'):
            from_ip, data = self.pending_invite
            self.is_host = False
            
            await self.mesh.send(from_ip, {
                'game_type': data.get('game_type'),
                'msg_type': 'game_accept',
                'player': self.mesh.virtual_ip
            })
            print(f"✅ Joined game!")
            del self.pending_invite
    
    async def make_move(self, move_data: dict):
        """Make a game move"""
        await self.mesh.broadcast({
            'game_type': self.game_state.game_type,
            'msg_type': 'game_move',
            'player': self.mesh.virtual_ip,
            'move': move_data
        })
    
    async def chat(self, message: str):
        """Send chat message in game"""
        await self.mesh.broadcast({
            'game_type': 'chat',
            'msg_type': 'game_chat',
            'message': message
        })
    
    def _render_game(self):
        """Render game state - override in subclass"""
        pass


class TicTacToe(P2PGame):
    """P2P Tic-Tac-Toe Game"""
    
    EMPTY = ' '
    
    def __init__(self, mesh: MeshNetwork):
        super().__init__(mesh)
        self.board = [[self.EMPTY] * 3 for _ in range(3)]
        self.symbols = {}  # player_ip -> X or O
    
    async def start_game(self):
        """Start a new Tic-Tac-Toe game"""
        await self.invite('tictactoe')
        self.board = [[self.EMPTY] * 3 for _ in range(3)]
        self.game_state.data = {'board': self.board}
        self.symbols[self.mesh.virtual_ip] = 'X'
        print("⏳ Waiting for opponent...")
    
    def _on_accept(self, from_ip: str, data: dict):
        super()._on_accept(from_ip, data)
        self.symbols[from_ip] = 'O'
        self._render_game()
        print(f"\n🎮 Game started! You are X. Your turn!")
    
    def _on_move(self, from_ip: str, data: dict):
        move = data.get('move', {})
        row, col = move.get('row'), move.get('col')
        symbol = self.symbols.get(from_ip, 'O')
        
        if self.board[row][col] == self.EMPTY:
            self.board[row][col] = symbol
            
            if self.is_host:
                self.game_state.data['board'] = self.board
                self.game_state.current_turn = self.mesh.virtual_ip
                asyncio.create_task(self._broadcast_state())
            
            self._render_game()
            
            winner = self._check_winner()
            if winner:
                print(f"\n🏆 {winner} wins!")
            elif self._is_draw():
                print(f"\n🤝 It's a draw!")
            else:
                print(f"\n📍 Your turn! Enter row,col (e.g., 1,1)")
    
    async def play(self, row: int, col: int):
        """Make a move"""
        if self.board[row][col] == self.EMPTY:
            symbol = self.symbols.get(self.mesh.virtual_ip, 'X')
            self.board[row][col] = symbol
            
            await self.make_move({'row': row, 'col': col})
            
            if self.is_host:
                peers = self.mesh.get_peers()
                if peers:
                    self.game_state.current_turn = peers[0].virtual_ip
                self.game_state.data['board'] = self.board
                await self._broadcast_state()
            
            self._render_game()
            
            winner = self._check_winner()
            if winner:
                print(f"\n🏆 {winner} wins!")
            elif self._is_draw():
                print(f"\n🤝 It's a draw!")
            else:
                print("⏳ Waiting for opponent...")
        else:
            print("❌ Cell already taken!")
    
    def _render_game(self):
        print("\n┌───┬───┬───┐")
        for i, row in enumerate(self.board):
            print(f"│ {row[0]} │ {row[1]} │ {row[2]} │")
            if i < 2:
                print("├───┼───┼───┤")
        print("└───┴───┴───┘")
    
    def _check_winner(self) -> Optional[str]:
        # Check rows, cols, diagonals
        lines = []
        lines.extend(self.board)  # rows
        lines.extend([[self.board[i][j] for i in range(3)] for j in range(3)])  # cols
        lines.append([self.board[i][i] for i in range(3)])  # diagonal
        lines.append([self.board[i][2-i] for i in range(3)])  # anti-diagonal
        
        for line in lines:
            if line[0] != self.EMPTY and line[0] == line[1] == line[2]:
                return line[0]
        return None
    
    def _is_draw(self) -> bool:
        return all(self.board[i][j] != self.EMPTY for i in range(3) for j in range(3))


class DrawingGame(P2PGame):
    """Simple P2P Drawing/Whiteboard"""
    
    def __init__(self, mesh: MeshNetwork):
        super().__init__(mesh)
        self.canvas: List[dict] = []  # List of drawing commands
    
    async def draw(self, x: int, y: int, color: str = 'white'):
        """Add a point to the canvas"""
        point = {'x': x, 'y': y, 'color': color, 'player': self.mesh.virtual_ip}
        self.canvas.append(point)
        await self.mesh.broadcast({
            'game_type': 'drawing',
            'msg_type': 'game_move',
            'move': point
        })
    
    def _on_move(self, from_ip: str, data: dict):
        point = data.get('move', {})
        self.canvas.append(point)
        print(f"🎨 {from_ip} drew at ({point.get('x')}, {point.get('y')})")


class QuizGame(P2PGame):
    """P2P Quiz Game"""
    
    def __init__(self, mesh: MeshNetwork):
        super().__init__(mesh)
        self.questions = [
            {"q": "What is 2+2?", "a": "4"},
            {"q": "Capital of France?", "a": "paris"},
            {"q": "Largest planet?", "a": "jupiter"},
        ]
        self.scores: Dict[str, int] = {}
        self.current_question = 0
    
    async def start_quiz(self):
        """Start quiz game"""
        await self.invite('quiz')
        self.scores[self.mesh.virtual_ip] = 0
        print("⏳ Waiting for players...")
    
    def _on_accept(self, from_ip: str, data: dict):
        super()._on_accept(from_ip, data)
        self.scores[from_ip] = 0
        asyncio.create_task(self._next_question())
    
    async def _next_question(self):
        if self.current_question < len(self.questions):
            q = self.questions[self.current_question]
            print(f"\n❓ Question {self.current_question + 1}: {q['q']}")
            await self.mesh.broadcast({
                'game_type': 'quiz',
                'msg_type': 'game_move',
                'move': {'question': q['q'], 'num': self.current_question}
            })
    
    async def answer(self, ans: str):
        """Submit answer"""
        q = self.questions[self.current_question]
        if ans.lower().strip() == q['a'].lower():
            self.scores[self.mesh.virtual_ip] = self.scores.get(self.mesh.virtual_ip, 0) + 1
            print("✅ Correct!")
        else:
            print(f"❌ Wrong! Answer was: {q['a']}")
        
        self.current_question += 1
        if self.is_host:
            await self._next_question()
        
        if self.current_question >= len(self.questions):
            print(f"\n📊 Final Scores: {self.scores}")


async def game_menu(mesh: MeshNetwork):
    """Interactive game menu"""
    print("\n" + "="*50)
    print("🎮 P2P GAME MENU")
    print("="*50)
    print("Commands:")
    print("  /tictactoe  - Start Tic-Tac-Toe")
    print("  /quiz       - Start Quiz Game")
    print("  /accept     - Accept game invite")
    print("  /move r,c   - Make move (e.g., /move 1,1)")
    print("  /peers      - List connected peers")
    print("  /chat msg   - Send chat message")
    print("  /quit       - Exit")
    print("="*50)
    
    ttt = TicTacToe(mesh)
    quiz = QuizGame(mesh)
    current_game = None
    
    loop = asyncio.get_event_loop()
    while True:
        try:
            cmd = await loop.run_in_executor(None, input, "\n> ")
            
            if cmd.startswith('/tictactoe'):
                current_game = ttt
                await ttt.start_game()
            
            elif cmd.startswith('/quiz'):
                current_game = quiz
                await quiz.start_quiz()
            
            elif cmd.startswith('/accept'):
                if current_game:
                    await current_game.accept_invite()
                else:
                    # Try to accept with ttt by default
                    ttt.pending_invite = getattr(ttt, 'pending_invite', None) or getattr(quiz, 'pending_invite', None)
                    if ttt.pending_invite:
                        current_game = ttt
                        await ttt.accept_invite()
            
            elif cmd.startswith('/move'):
                if isinstance(current_game, TicTacToe):
                    parts = cmd.split()[1].split(',')
                    row, col = int(parts[0]), int(parts[1])
                    await ttt.play(row, col)
            
            elif cmd.startswith('/answer'):
                if isinstance(current_game, QuizGame):
                    ans = cmd.split(' ', 1)[1]
                    await quiz.answer(ans)
            
            elif cmd.startswith('/peers'):
                print("\n📋 Connected peers:")
                for p in mesh.get_peers():
                    print(f"   {p.virtual_ip} - {p.external_ip}:{p.external_port}")
            
            elif cmd.startswith('/chat'):
                msg = cmd.split(' ', 1)[1] if ' ' in cmd else ''
                await mesh.broadcast({'type': 'chat', 'msg': msg})
            
            elif cmd.startswith('/quit'):
                break
            
            else:
                # Regular chat
                if cmd.strip():
                    await mesh.broadcast(cmd)
                    
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='P2P Games')
    parser.add_argument('--network', '-n', default='game-network', help='Network name')
    parser.add_argument('--secret', '-s', default='game-secret-123', help='Network secret')
    parser.add_argument('--port', '-p', type=int, default=0, help='Local port')
    parser.add_argument('--connect', '-c', help='Connect to peer (ip:port)')
    
    args = parser.parse_args()
    
    # Create mesh network
    mesh = MeshNetwork(args.network, args.secret, args.port)
    await mesh.start()
    
    # Connect to peer if specified
    if args.connect:
        ip, port = args.connect.split(':')
        print(f"\n🔗 Connecting to {ip}:{port}...")
        await mesh.connect_to_peer(ip, int(port))
        await asyncio.sleep(2)  # Wait for connection
    else:
        print(f"\n📱 Share with friends:")
        print(f"   python p2p_game.py -n {args.network} -s {args.secret} -c {mesh.external_ip}:{mesh.external_port}")
    
    await game_menu(mesh)
    print("\n👋 Thanks for playing!")


if __name__ == "__main__":
    asyncio.run(main())
