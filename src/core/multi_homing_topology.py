import copy
import itertools
import logging

from .topology import ITopology, MatrixType


class MultiHomingTopology(ITopology):
    """Two-node multi-homing topology expanded from path vectors."""

    # The matrices retain their historical representation for routing and
    # compatibility.  Physical-link attributes are stored separately because
    # the two matrix cells represent parallel links, not opposite directions.
    is_multihoming = True

    PATH_INDEX_TO_CELL = {
        0: (0, 1),
        1: (1, 0),
    }

    def __init__(self, base_path: str, top_config, init_all_mats=True):
        super().__init__(base_path, top_config, False)
        if init_all_mats:
            self._init_topologies()

    def description(self) -> str:
        if not self.all_mats:
            return "Multi-homing topology"
        path_descriptions = []
        for path in self._path_descriptions():
            attributes = self.multihoming_link_attributes.get(path["index"])
            path_descriptions.append(
                f"{path['name']}: "
                f"bandwidth {attributes['bw']}Mbps,"
                f"latency {attributes['rtt']}ms,"
                f"loss {attributes['loss']}%,"
                f"jitter {attributes['jitter']}ms"
            )
        return "Multi-homing h0-h1\n" + "\n".join(path_descriptions)

    def ascii_art(self) -> str:
        if not self.all_mats:
            return ""
        return "\n".join(
            f"h0 <----({link['bw']},{link['rtt']}ms,{link['loss']}%)-----> h1"
            for link in self.multihoming_link_attributes.values())

    def generate_adj_matrix(self, num_of_nodes: int):
        if num_of_nodes != 2:
            raise ValueError("Multi-homing path_description requires exactly 2 nodes.")
        return [
            [0, 1],
            [1, 0],
        ]

    def generate_other_matrices(self, adj_matrix):
        pass

    def _init_topologies(self):
        self.compound_top = True
        self._validate_path_description()
        adjacency = self.generate_adj_matrix(self.top_config.nodes)
        path_options = [
            self._path_options(path) for path in self._path_descriptions()
        ]

        for selected_options in itertools.product(*path_options):
            topology = MultiHomingTopology(
                self.conf_base_path, self.top_config, False)
            topology.all_mats[MatrixType.ADJACENCY_MATRIX] = copy.deepcopy(
                adjacency)
            topology.all_mats[MatrixType.BW_MATRIX] = self._empty_matrix()
            topology.all_mats[MatrixType.LOSS_MATRIX] = self._empty_matrix()
            topology.all_mats[MatrixType.LATENCY_MATRIX] = self._empty_matrix()
            topology.all_mats[MatrixType.JITTER_MATRIX] = self._empty_matrix()
            topology.multihoming_link_attributes = {}

            for option in selected_options:
                row, col = self.PATH_INDEX_TO_CELL[option["index"]]
                topology.multihoming_link_attributes[option["index"]] = copy.deepcopy(option)
                topology.all_mats[MatrixType.BW_MATRIX][row][col] = option["bw"]
                topology.all_mats[MatrixType.LOSS_MATRIX][row][col] = option["loss"]
                topology.all_mats[MatrixType.LATENCY_MATRIX][row][col] = option["rtt"]
                topology.all_mats[MatrixType.JITTER_MATRIX][row][col] = option["jitter"]

            logging.debug(
                "Added MultiHomingTopology %s", topology.all_mats)
            self.topologies.append(topology)

    def _validate_path_description(self):
        paths = self._path_descriptions()
        if not paths:
            raise ValueError("path_description is required for multi-homing topology.")
        path_indexes = {path.get("index") for path in paths}
        expected_indexes = set(self.PATH_INDEX_TO_CELL.keys())
        if path_indexes != expected_indexes:
            raise ValueError(
                "path_description must define paths with indexes 0 and 1.")
        for path in paths:
            for vector_name in ("bw_vector", "rtt_vector", "loss_vector", "jitter_vector"):
                if vector_name not in path or not path[vector_name]:
                    raise ValueError(
                        f"path_description {path.get('name', path.get('index'))} "
                        f"must define a non-empty {vector_name}.")

    def _path_descriptions(self):
        return sorted(
            self.top_config.path_description or [],
            key=lambda path: path.get("index", 0))

    @staticmethod
    def _empty_matrix():
        return [
            [0, 0],
            [0, 0],
        ]

    @staticmethod
    def _path_options(path):
        options = []
        for bw, rtt, loss, jitter in itertools.product(
                path["bw_vector"],
                path["rtt_vector"],
                path["loss_vector"],
                path["jitter_vector"]):
            options.append({
                "name": path.get("name", f"path{path['index']}"),
                "index": path["index"],
                "bw": bw,
                "rtt": rtt,
                "loss": loss,
                "jitter": jitter,
            })
        return options
