#####################################################
# LSrouter.py
# Name:
# HUID:
#####################################################

import json
import heapq
from router import Router
from packet import Packet


class LSrouter(Router):
    def __init__(self, addr, heartbeat_time):
        Router.__init__(self, addr)  
        self.heartbeat_time = heartbeat_time  
        self.last_time = 0                   

        self.neighbors = {} # port : (đ/c neighbor, cost)
        self.addr_to_port = {} # biết đ/c neighbor -> tìm port tương ứng

        # Lưu thông tin topology của toàn bộ mạng mà router này biết
        # router_addr -> {"seq": stt, "links": {neighbor: cost}}
        self.link_state_db = {
            self.addr: {"seq": 0, "links": {}}  
        }
        self.lsa_seq = 0 # Stt LSA của router để neighbor biết bản tin nào mới, tránh xử lý bản cũ
        self.forwarding_table = {} # Bảng chuyển tiếp, đích : port 

    def broadcast_lsa(self, exclude_port=None):
        """
        Tạo LSA của chính router này rồi gửi cho tất cả neighbor (trừ cổng exclude_port).
        """
        # Tăng stt để neighbor biết đây là bản tin mới
        self.lsa_seq += 1
        self.link_state_db[self.addr]["seq"] = self.lsa_seq

        # Đóng gói nội dung LSA thành JSON để gửi đi
        content = json.dumps({
            "src":   self.addr,
            "seq":   self.lsa_seq,
            "links": self.link_state_db[self.addr]["links"]
        })

        # Gửi cho từng neighbor trực tiếp
        for port in self.neighbors:
            if port == exclude_port:
                continue  # Bỏ qua cổng nhận LSA vào
            pkt = Packet(Packet.ROUTING, self.addr,
                         self.neighbors[port][0], content)
            self.send(port, pkt)

    def flood_lsa(self, lsa_content, exclude_port=None):
        """
        Chuyển tiếp LSA nhận được từ router khác tới tất cả neighbor, trừ exclude_port.
        """
        for port, (neighbor, _) in self.neighbors.items():
            if port == exclude_port:
                continue  # Không gửi ngược lại nơi vừa nhận
            pkt = Packet(Packet.ROUTING, self.addr,
                         neighbor, json.dumps(lsa_content))
            self.send(port, pkt)

    def dijkstra(self):
        """
        Thuật toán Dijkstra trên link_state_db tìm đường ngắn nhất từ router này tới mọi đích trong mạng.
        """
        dist = {self.addr: 0}
        out_port = {}
        heap = [(0, self.addr)] # (cost, địa chỉ node)

        while heap:
            cost, node = heapq.heappop(heap)  
            if cost > dist.get(node, float("inf")):
                continue
            if node not in self.link_state_db:
                continue

            # Xét tất cả neighbor của node hiện tại
            for neighbor, link_cost in self.link_state_db[node]["links"].items():
                new_cost = cost + link_cost  

                # Cập nhật nếu tìm được đường rẻ hơn
                if new_cost < dist.get(neighbor, float("inf")):
                    dist[neighbor] = new_cost

                    # Xác định cổng ra:
                    if node == self.addr:
                        # Node hiện tại là chính mình -> direct neighbor -> tra addr_to_port để biết cổng ra
                        port = self.addr_to_port.get(neighbor)
                        if port is not None:
                            out_port[neighbor] = port
                    else:
                        # Node hiện tại là router trung gian -> kế thừa cổng ra từ node trung gian đó
                        if node in out_port:
                            out_port[neighbor] = out_port[node]

                    heapq.heappush(heap, (new_cost, neighbor))

        # Xây dựng lại forwarding_table từ out_port, không forward tới chính mình
        self.forwarding_table = {
            dst: port
            for dst, port in out_port.items()
            if dst != self.addr
        }

    def handle_packet(self, port, packet):
        """Xử lý packet đến từ một cổng."""
        if packet.is_traceroute:
            # Packet dữ liệu thông thường -> tra forwarding_table rồi chuyển tiếp
            dst = packet.dst_addr
            if dst in self.forwarding_table:
                self.send(self.forwarding_table[dst], packet)
        else:
            # Packet định tuyến -> đây là LSA từ router khác
            try:
                lsa = json.loads(packet.content)  # Giải mã JSON, lỗi -> bỏ qua
            except (json.JSONDecodeError, AttributeError):
                return  

            src   = lsa.get("src")    
            seq   = lsa.get("seq")    
            links = lsa.get("links", {})  
            if src is None or seq is None:
                return  
            # Chỉ xử lý nếu LSA này mới hơn
            if src in self.link_state_db and self.link_state_db[src]["seq"] >= seq:
                return  

            # Cập nhật link_state_db với thông tin mới 
            self.link_state_db[src] = {"seq": seq, "links": links}
            # Tính lại đường đi 
            self.dijkstra()
            # Flood LSA này cho các neighbor khác 
            self.flood_lsa(lsa, exclude_port=port)

    def handle_new_link(self, port, endpoint, cost):
        """Xử lý khi có link mới được kết nối vào router này."""
        # Ghi nhận link mới vào neighbor
        self.neighbors[port] = (endpoint, cost)
        self.addr_to_port[endpoint] = port  # Lưu ngược để Dijkstra tra được
        self.link_state_db[self.addr]["links"][endpoint] = cost

        self.dijkstra()
        # Thông báo cho cả mạng biết topology của mình vừa thay đổi
        self.broadcast_lsa()

    def handle_remove_link(self, port):
        """Xử lý khi một link bị ngắt kết nối."""
        if port not in self.neighbors:
            return
        # Xóa link khỏi neighbor
        endpoint, _ = self.neighbors.pop(port)
        self.addr_to_port.pop(endpoint, None)
        self.link_state_db[self.addr]["links"].pop(endpoint, None)
        
        self.dijkstra()
        self.broadcast_lsa()

    def handle_time(self, time_ms):
        """Gửi LSA định kỳ để cả mạng biết router này vẫn còn sống."""
        if time_ms - self.last_time >= self.heartbeat_time:
            self.last_time = time_ms
            self.broadcast_lsa()

    def __repr__(self):
        """Hiển thị thông tin router khi debug trong network visualizer."""
        return (
            f"LSrouter(addr={self.addr}, "
            f"neighbors={list(self.neighbors.values())}, "
            f"fwd={self.forwarding_table})"
        )