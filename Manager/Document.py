# ************************************************************************
# *   Copyright (c) Stefan Troeger (stefantroeger@gmx.net) 2021          *
# *                                                                      *
# *   This library is free software; you can redistribute it and/or      *
# *   modify it under the terms of the GNU Library General Public        *
# *   License as published by the Free Software Foundation; either       *
# *   version 2 of the License, or (at your option) any later version.   *
# *                                                                      *
# *   This library  is distributed in the hope that it will be useful,   *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of     *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the      *
# *   GNU Library General Public License for more details.               *
# *                                                                      *
# *   You should have received a copy of the GNU Library General Public  *
# *   License along with this library; see the file COPYING.LIB. If not, *
# *   write to the Free Software Foundation, Inc., 59 Temple Place,      *
# *   Suite 330, Boston, MA  02111-1307, USA                             *
# ************************************************************************

import asyncio
import Helper
from enum import Enum, auto
from PySide import QtCore
from qasync import asyncSlot


class PeerModel(QtCore.QAbstractListModel):
    # Data model handling peers in a document
    
    class Roles(Enum):
        nodeid          = auto()
        authorisation   = auto()
        joined          = auto()


    def __init__(self):
        QtCore.QAbstractListModel.__init__(self)
        
        self.__peers = [] # peers are dicts with data for each role
        
    
    def __getPeer(self, id):
        for peer in self.__peers:
            if peer[PeerModel.Roles.nodeid] == id:
                return  peer
        
        return None
    
    def clear(self):
        self.layoutAboutToBeChanged.emit()
        self.__peers = []
        self.layoutChanged.emit()
    
    
    def addPeer(self, nodeid, auth, joined):
        
        if self.__getPeer(nodeid):
            raise Exception("Cannot add peer, already in model")
        
        peer = {PeerModel.Roles.nodeid: nodeid,  
                PeerModel.Roles.authorisation: auth, 
                PeerModel.Roles.joined:  joined}
        
        self.layoutAboutToBeChanged.emit()
        self.__peers.append(peer)
        self.layoutChanged.emit()
        
    
    def removePeer(self, nodeid):
        
        peer = self.__getPeer(nodeid)
        if peer:
            self.layoutAboutToBeChanged.emit()
            self.__peers.remove(peer)
            self.layoutChanged.emit()
    
    
    def changePeer(self, nodeid, role, data):
        
        peer = self.__getPeer(nodeid)
        if peer:
            self.layoutAboutToBeChanged.emit()
            peer[role]  = data
            self.layoutChanged.emit()
            
    def peerByIndex(self, idx):
        return self.__peers[idx][PeerModel.Roles.nodeid]
    
    def peerAuthByIndex(self, idx):
        return self.__peers[idx][PeerModel.Roles.authorisation]
            
    def peerCount(self):
        return len(self.__peers)
    
    def joinedCount(self):        
        count = 0
        for peer in self.__peers:
            if peer[PeerModel.Roles.joined]:
                count += 1
        
        return count
    
    
    # QT Model implementation
    # *************************
        
    def roleNames(self):
        result = {}
        for role in PeerModel.Roles:
            result[role.value] = QtCore.QByteArray(bytes(role.name, 'utf-8'))
        
        return result

    def data(self, index, role):

        peer = self.__peers[index.row()]        
        return peer[PeerModel.Roles(role)]

    def rowCount(self, index):
        return len(self.__peers)


class ManagedDocument(QtCore.QObject, Helper.AsyncSlotObject):
    # Helps to manage documents on the OCP node, manages naming and peers
    
    def __init__(self, id, connection):
        QtCore.QObject.__init__(self)
        
        self.__peers = PeerModel()
        self.__docId = id
        self.__connection = connection
        self.__readyEvt = asyncio.Event()
        
        connection.api.connectedChanged.connect(self.__connectChanged)
        asyncio.ensure_future(self.__asyncInit())
        
    
    async def __asyncInit(self):
        
        # fetch the currently registered peers as well as the active ones
        # (no await, as is async slot)
        self.__connectChanged()
        
        # subscribe to peer update, registration and active
        self.__subkey = f"ManagedDocument_{self.__docId}"
        await self.__connection.api.subscribe(self.__subkey, self.__peerAuthChanged,  f"ocp.documents.{self.__docId}.peerAuthChanged")
        await self.__connection.api.subscribe(self.__subkey, self.__peerActivityChanged,  f"ocp.documents.{self.__docId}.peerActivityChanged")
        await self.__connection.api.subscribe(self.__subkey, self.__peerAdded,  f"ocp.documents.{self.__docId}.peerAdded")
        await self.__connection.api.subscribe(self.__subkey, self.__peerRemoved,  f"ocp.documents.{self.__docId}.peerRemoved")
        self.__readyEvt.set()
        
    async def ready(self):
        await self.__readyEvt.wait()

    async def close(self):
        #unsubscribe the events
        await self.__connection.api.closeKey(self.__subkey)
    
    
    # Managing functions
    # *************************************************************
    
    async def addPeer(self, peer, auth):
        
        uri = f"ocp.documents.{self.__docId}.addPeer"
        await self.__connection.api.call(uri, peer, auth)
    
    async def removePeer(self, peer):
        
        uri = f"ocp.documents.{self.__docId}.removePeer"
        await self.__connection.api.call(uri, peer)
    
    async def changePeerAuth(self, peer, auth):
        
        uri = f"ocp.documents.{self.__docId}.setPeerAuth"
        await self.__connection.api.call(uri, peer, auth)
    
        
    # Callbacks, OCP API and node document
    # *************************************************************
    
    @asyncSlot()
    async def __connectChanged(self):
        
        if self.__connection.api.connected:
            readPeers = await self.__connection.api.call(f"ocp.documents.{self.__docId}.listPeers", auth="Read")
            writePeers = await self.__connection.api.call(f"ocp.documents.{self.__docId}.listPeers", auth="Write")
            joinedPeers = await self.__connection.api.call(f"ocp.documents.{self.__docId}.listPeers", joined=True)
            
            for peer in readPeers:
                self.__peers.addPeer(peer, "Read", peer in joinedPeers)
            
            for peer in writePeers:
                self.__peers.addPeer(peer, "Write", peer in joinedPeers)
            
            self.__memberCountChanged.emit()
            self.__joinedCountChanged.emit()
            
        else:
            self.__peers.clear()
            self.__memberCountChanged.emit()
            self.__joinedCountChanged.emit()
            
            
    async def __peerAuthChanged(self, peer, auth):
        self.__peers.changePeer(peer, PeerModel.Roles.authorisation, auth)
    
    async def __peerActivityChanged(self, peer, joined):
        self.__peers.changePeer(peer, PeerModel.Roles.joined, joined)
        self.__joinedCountChanged.emit()
    
    async def __peerAdded(self, peer, auth):
        self.__peers.addPeer(peer, auth, False)
        self.__memberCountChanged.emit()
    
    async def __peerRemoved(self, peer):
        self.__peers.removePeer(peer)
        self.__memberCountChanged.emit()


    def __getPeers(self):
        return self.__peers

    def __getName(self):
        return "ToBeImplemented"
    
    def __getMemberCount(self):
        return self.__peers.peerCount()
    
    def __getJoinedCount(self):
        return self.__peers.joinedCount()

    __nameChanged = QtCore.Signal()
    __memberCountChanged = QtCore.Signal()
    __joinedCountChanged = QtCore.Signal()
    
    name = QtCore.Property(str, __getName, notify=__nameChanged)
    peers = QtCore.Property(QtCore.QObject, __getPeers, constant=True)
    memberCount = QtCore.Property(int, __getMemberCount, notify=__memberCountChanged)
    joinedCount = QtCore.Property(int, __getJoinedCount, notify=__joinedCountChanged)

    @Helper.AsyncSlot(str)
    def setNameSlot(self, name):
        print(f"SetName with {name}")

    @Helper.AsyncSlot(int)
    async def removePeerSlot(self, idx):
        peer = self.__peers.peerByIndex(idx)
        await self.removePeer(peer)

    @Helper.AsyncSlot(int)
    async def togglePeerRigthsSlot(self, idx):
        
        peer = self.__peers.peerByIndex(idx)
        auth = self.__peers.peerAuthByIndex(idx)
        if auth == "Write":
            await self.changePeerAuth(peer, "Read")
        else:
            await self.changePeerAuth(peer, "Write")

    @Helper.AsyncSlot(str, bool)
    async def addPeerSlot(self, id, edit):
        auth = "Read"
        if edit:
            auth = "Write"
                
        await self.addPeer(id, auth)