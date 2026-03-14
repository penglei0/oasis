from abc import ABC, abstractmethod
from enum import IntEnum

from dataclasses import dataclass, field
from typing import Optional, List
import logging
import os
import json


class LinkAttr(IntEnum):
    link_loss = 0
    link_latency = 1
    link_jitter = 2
    link_bandwidth_forward = 3
    link_bandwidth_backward = 4


class MatrixType(IntEnum):
    # Adjacency matrix to describe the network topology
    ADJACENCY_MATRIX = 0
    # Bandwidth matrix to describe the network bandwidth link-by-link
    BW_MATRIX = 1
    # Loss matrix to describe the network loss link-by-link
    LOSS_MATRIX = 2
    # Latency matrix to describe the network latency link-by-link
    LATENCY_MATRIX = 3
    # Jitter matrix to describe the network jitter link-by-link
    JITTER_MATRIX = 4


# mapping MatrixType to the link attribute except for the adjacency matrix
MatType2LinkAttr = {
    MatrixType.LOSS_MATRIX: LinkAttr.link_loss,
    MatrixType.LATENCY_MATRIX: LinkAttr.link_latency,
    MatrixType.JITTER_MATRIX: LinkAttr.link_jitter,
    MatrixType.BW_MATRIX: LinkAttr.link_bandwidth_forward
}


class TopologyType(IntEnum):
    linear = 0      # Linear chain topology
    star = 1        # Star topology
    tree = 2        # Complete Binary Tree
    butterfly = 3   # Butterfly topology
    mesh = 5        # Random Mesh topology


@dataclass
class Parameter:
    name: str
    init_value: List[int]


@dataclass
class TopologyConfig:
    """Configuration for the network topology.
    """
    name: str
    nodes: int
    topology_type: TopologyType
    # @array_description: the array description of the topology
    array_description: Optional[List[Parameter]] = field(default=None)
    # @json_description: the json description of the topology
    json_description: Optional[str] = field(default=None)


class ITopology(ABC):
    # Extra gap so the left/right vertical link labels do not crowd each other.
    RECTANGLE_INNER_PADDING = 8
    RECTANGLE_NODE_ORDER = [0, 1, 2, 3]

    def __init__(self, base_path: str, top: TopologyConfig, init_all_mat: bool = True):
        self.conf_base_path = base_path
        self.all_mats = {}
        self.adj_matrix = None
        self.top_config = top
        self.compound_top = False
        self._current_top_index = 0  # keep track of the current topology
        # when compound_top is True, the topologies is a list of ITopology;
        # otherwise, it is empty.
        self.topologies = []
        if init_all_mat is True:
            self.init_all_mats()

    def __iter__(self):
        return iter(self.topologies)

    @abstractmethod
    def description(self) -> str:
        pass

    def ascii_art(self) -> str:
        """Render the current topology using a small ASCII diagram."""
        adj_matrix = self.get_matrix(MatrixType.ADJACENCY_MATRIX)
        if adj_matrix is None:
            return ""
        if self._is_chain(adj_matrix):
            return self._render_chain(adj_matrix)
        if self._is_star(adj_matrix):
            return self._render_star(adj_matrix)
        if self._is_diamond(adj_matrix):
            return self._render_diamond(adj_matrix)
        if self._is_rectangle(adj_matrix):
            return self._render_rectangle(adj_matrix)
        return self._render_links(adj_matrix)

    def get_next_top(self):
        if not self.is_compound():
            logging.error("get_next_top() called on a non-compound topology.")
            return None
        if self._current_top_index >= len(self.topologies):
            logging.info("No more compound topologies available.")
            return None
        top = self.topologies[self._current_top_index]
        logging.info("########## Use Oasis compound topology %s.",
                     self._current_top_index)
        self._current_top_index += 1
        return top

    def is_compound(self):
        return self.compound_top

    @abstractmethod
    def generate_adj_matrix(self, num_of_nodes: int):
        pass

    @abstractmethod
    def generate_other_matrices(self, adj_matrix):
        pass

    def get_topology_type(self):
        return self.top_config.topology_type

    def get_matrix(self, mat_type: MatrixType):
        # when invoked, compound_top is expected to be False
        if self.is_compound():
            logging.error("Incorrect usage of compound topology get_matrix()")
        if mat_type not in self.all_mats:
            return None
        return self.all_mats[mat_type]

    def init_all_mats(self):
        # init from json_description or array_description
        if self.top_config.json_description is not None:
            logging.debug(
                'Load the matrix from json_description')
            self.load_all_mats(
                self.top_config.json_description)
        elif self.top_config.array_description is not None:
            logging.debug(
                'Load the matrix from array_description')
            self.adj_matrix = self.generate_adj_matrix(self.top_config.nodes)
            self.all_mats[MatrixType.ADJACENCY_MATRIX] = self.adj_matrix
            self.generate_other_matrices(self.adj_matrix)

    def load_all_mats(self, json_file_path):
        """Load all matrices from the Json file.
        Args:
            json_file_path (string): The path of the Json file 
            which save the matrix.
            An example: 
                test/mesh-network.json
        """
        if json_file_path and not os.path.isabs(json_file_path):
            json_file_path = os.path.join(self.conf_base_path, json_file_path)
        logging.info(f"Loading matrix from Json file: %s", json_file_path)
        if not os.path.exists(json_file_path):
            raise ValueError(f"Json File {json_file_path} does not exist.")
        with open(json_file_path, 'r', encoding='utf-8') as f:
            json_content = json.load(f)
        if json_content is None:
            raise ValueError("The content of the Json file is None.")
        for mat_desc in json_content['data']:
            if 'matrix_type' not in mat_desc or 'matrix_data' not in mat_desc:
                continue
            logging.info(f"Matrix data: %s", mat_desc['matrix_data'])
            self.all_mats[mat_desc['matrix_type']] = mat_desc['matrix_data']

    def _render_chain(self, adj_matrix):
        chain_nodes = self._chain_order(adj_matrix)
        if not chain_nodes:
            return self._render_links(adj_matrix)
        rendered = [self._host_name(chain_nodes[0])]
        for left_node, right_node in zip(chain_nodes, chain_nodes[1:]):
            rendered.append(
                f"<----{self._link_label(left_node, right_node)}----->")
            rendered.append(self._host_name(right_node))
        return " ".join(rendered)

    def _render_star(self, adj_matrix):
        degrees = self._degrees(adj_matrix)
        center = next(
            (index for index, degree in enumerate(degrees)
             if degree == len(adj_matrix) - 1),
            None
        )
        if center is None:
            return self._render_links(adj_matrix)
        leaves = [index for index, connected in enumerate(adj_matrix[center])
                  if connected]
        if not leaves:
            return self._host_name(center)

        lines = []
        top_leaf = leaves[0]
        lines.extend([
            f"                {self._host_name(top_leaf)}",
            "                |",
            f"       {self._link_label(center, top_leaf)}",
            "                |"
        ])

        remaining_leaves = leaves[1:]
        if remaining_leaves:
            left_leaf = remaining_leaves[0]
            center_line = (
                f"{self._host_name(left_leaf)} <----"
                f"{self._link_label(left_leaf, center)}-----> "
                f"{self._host_name(center)}"
            )
            if len(remaining_leaves) > 1:
                right_leaf = remaining_leaves[1]
                center_line += (
                    f" <----{self._link_label(center, right_leaf)}-----> "
                    f"{self._host_name(right_leaf)}"
                )
            lines.append(center_line)
            for extra_leaf in remaining_leaves[2:]:
                lines.extend([
                    "                |",
                    f"       {self._link_label(center, extra_leaf)}",
                    "                |",
                    f"                {self._host_name(extra_leaf)}"
                ])
        else:
            lines.append(f"                {self._host_name(center)}")
        return "\n".join(lines)

    def _render_diamond(self, adj_matrix):
        groups = self._diamond_groups(adj_matrix)
        if groups is None:
            return self._render_links(adj_matrix)
        endpoints, middle_nodes = groups
        left_node = min(endpoints)
        right_node = max(endpoints)
        top_node = min(middle_nodes)
        bottom_node = max(middle_nodes)
        return "\n".join([
            f"{self._host_name(left_node)} <----"
            f"{self._link_label(left_node, top_node)}-----> "
            f"{self._host_name(top_node)} <----"
            f"{self._link_label(top_node, right_node)}-----> "
            f"{self._host_name(right_node)}",
            f"{self._host_name(left_node)} <----"
            f"{self._link_label(left_node, bottom_node)}-----> "
            f"{self._host_name(bottom_node)} <----"
            f"{self._link_label(bottom_node, right_node)}-----> "
            f"{self._host_name(right_node)}"
        ])

    def _render_rectangle(self, adj_matrix):
        cycle = self._rectangle_cycle(adj_matrix)
        if cycle is None:
            return self._render_links(adj_matrix)
        top_left, top_right, bottom_right, bottom_left = cycle
        vertical_width = max(
            len(self._link_label(top_left, bottom_left)),
            len(self._link_label(top_right, bottom_right))
        ) + 2
        horizontal_width = max(
            len(self._link_label(top_left, top_right)),
            len(self._link_label(bottom_left, bottom_right))
        ) + self.RECTANGLE_INNER_PADDING
        left_vertical = self._link_label(top_left, bottom_left).ljust(
            vertical_width)
        right_vertical = self._link_label(top_right, bottom_right).ljust(
            vertical_width)
        return "\n".join([
            f"{self._host_name(top_left)} <----"
            f"{self._link_label(top_left, top_right)}-----> "
            f"{self._host_name(top_right)}",
            f"| {left_vertical}{' ' * horizontal_width}| {right_vertical}|",
            f"{self._host_name(bottom_left)} <----"
            f"{self._link_label(bottom_left, bottom_right)}-----> "
            f"{self._host_name(bottom_right)}"
        ])

    def _render_links(self, adj_matrix):
        rendered_links = []
        for row_index in range(len(adj_matrix)):
            for col_index in range(row_index + 1, len(adj_matrix)):
                if adj_matrix[row_index][col_index]:
                    rendered_links.append(
                        f"{self._host_name(row_index)} <----"
                        f"{self._link_label(row_index, col_index)}-----> "
                        f"{self._host_name(col_index)}"
                    )
        return "\n".join(rendered_links)

    @staticmethod
    def _host_name(host_index):
        return f"h{host_index}"

    def _link_label(self, host1, host2):
        return (
            f"({self._matrix_value(MatrixType.BW_MATRIX, host1, host2)},"
            f"{self._matrix_value(MatrixType.LATENCY_MATRIX, host1, host2)}ms,"
            f"{self._matrix_value(MatrixType.LOSS_MATRIX, host1, host2)}%)"
        )

    def _matrix_value(self, matrix_type, row, col):
        matrix = self.get_matrix(matrix_type)
        if matrix is None:
            return "?"
        return self._format_value(matrix[row][col])

    @staticmethod
    def _format_value(value):
        if isinstance(value, float):
            return format(value, 'g')
        return str(value)

    @staticmethod
    def _degrees(adj_matrix):
        return [sum(row) for row in adj_matrix]

    def _is_connected(self, adj_matrix):
        if not adj_matrix:
            return False
        visited = set()
        stack = [0]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            for neighbor, connected in enumerate(adj_matrix[node]):
                if connected and neighbor not in visited:
                    stack.append(neighbor)
        return len(visited) == len(adj_matrix)

    def _is_chain(self, adj_matrix):
        if not self._is_connected(adj_matrix):
            return False
        degrees = self._degrees(adj_matrix)
        if len(adj_matrix) == 1:
            return True
        return degrees.count(1) == 2 and all(
            degree in (1, 2) for degree in degrees
        )

    def _is_star(self, adj_matrix):
        if len(adj_matrix) < 3 or not self._is_connected(adj_matrix):
            return False
        degrees = self._degrees(adj_matrix)
        return (
            degrees.count(len(adj_matrix) - 1) == 1 and
            degrees.count(1) == len(adj_matrix) - 1
        )

    def _is_diamond(self, adj_matrix):
        return self._diamond_groups(adj_matrix) is not None

    def _diamond_groups(self, adj_matrix):
        if len(adj_matrix) != 4 or not self._is_connected(adj_matrix):
            return None
        if self._rectangle_cycle(adj_matrix) is not None:
            return None
        degrees = self._degrees(adj_matrix)
        if any(degree != 2 for degree in degrees):
            return None
        neighbor_sets = {}
        for node, row in enumerate(adj_matrix):
            key = tuple(index for index, connected in enumerate(row) if connected)
            neighbor_sets.setdefault(key, []).append(node)
        if len(neighbor_sets) != 2:
            return None
        grouped_nodes = [sorted(nodes) for nodes in neighbor_sets.values()]
        if any(len(nodes) != 2 for nodes in grouped_nodes):
            return None
        grouped_nodes.sort(key=lambda nodes: min(nodes))
        return grouped_nodes[0], grouped_nodes[1]

    def _is_rectangle(self, adj_matrix):
        return self._rectangle_cycle(adj_matrix) is not None

    def _rectangle_cycle(self, adj_matrix):
        if len(adj_matrix) != 4 or not self._is_connected(adj_matrix):
            return None
        degrees = self._degrees(adj_matrix)
        if any(degree != 2 for degree in degrees):
            return None
        # Rectangle layouts are expected to number hosts around the perimeter
        # in display order (h0-h1-h2-h3). Diamond layouts use a different
        # numbering pattern and fall through to _diamond_groups().
        cycle = self.RECTANGLE_NODE_ORDER
        expected_edges = [
            (cycle[0], cycle[1]),
            (cycle[1], cycle[2]),
            (cycle[2], cycle[3]),
            (cycle[3], cycle[0]),
        ]
        if all(adj_matrix[left][right] for left, right in expected_edges):
            return cycle
        return None

    def _chain_order(self, adj_matrix):
        if len(adj_matrix) == 1:
            return [0]
        endpoints = [index for index, degree in enumerate(self._degrees(adj_matrix))
                     if degree == 1]
        if len(endpoints) != 2:
            return []
        order = [min(endpoints)]
        previous = None
        while len(order) < len(adj_matrix):
            current = order[-1]
            next_nodes = [
                index for index, connected in enumerate(adj_matrix[current])
                if connected and index != previous
            ]
            if not next_nodes:
                break
            next_node = next_nodes[0]
            order.append(next_node)
            previous = current
        return order
