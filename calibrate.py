#!/usr/bin/env python

from __future__ import print_function, division
import sys
import os.path
from copy import copy
import time
from datetime import datetime
import argparse
import xml.etree.ElementTree as ET
import csv
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import PyKDL
import rospy
import dvrk
from analyze_data import get_offset_v_error, get_best_fit_plane, get_poly_min
from marker import Marker
from cisstNumericalPython import nmrRegistrationRigid

class Calibration(object):

    ROT_MATRIX = PyKDL.Rotation(
        1,    0,    0,
        0,   -1,    0,
        0,    0,   -1
    )

    def __init__(self, robot_name):
        print("initializing calibration for", robot_name)
        print("have a flat surface below the robot")
        self.data = []
        self.polaris = False
        self.info = {}
        # Add checker for directory
        strdate = time.strftime("%Y-%m-%d_%H-%M-%S")
        self.folder = os.path.join("data", "{}_{}".format(robot_name, strdate))
        os.mkdir(self.folder)
        print("Created folder at {}".format(os.path.abspath(self.folder)))

        self.arm = dvrk.psm(robot_name)
        self.home()

    def home(self):
        "Goes to x = 0, y = 0, extends joint 2 past the cannula, and sets home"
        # make sure the camera is past the cannula and tool vertical
        print("starting home")
        self.arm.home()
        self.arm.close_jaw()

        if self.arm.get_current_joint_position()[2] > 0.12:
            # Already past cannula
            carte_goal = self.arm.get_current_position().p
            carte_goal[2] += 0.04
            self.arm.move(carte_goal)

        goal = np.zeros(6)

        if ((self.arm.name() == 'PSM1') or (self.arm.name() == 'PSM2') or
            (self.arm.name() == 'PSM3') or (self.arm.name() == 'ECM')):
            # set in position joint mode
            goal[2] = 0.08
            self.arm.move_joint(goal)
        self.arm.move(self.ROT_MATRIX)

    def output_to_csv(self):
        """Outputs contents of self.data to fpath"""
        filename = "plane.csv" if not self.polaris else "polaris_point_cloud.csv"
        self.info["polaris"] = self.polaris
        with open(os.path.join(self.folder, "info.txt"), 'w') as infofile:
            for key, val in self.info.iteritems():
                infofile.write("{}: {}\n".format(key, val))

        with open(os.path.join(self.folder, filename), 'w') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.data[0].keys())
            writer.writeheader()
            writer.writerows(self.data)


def choose_filename(fpath):
    """checks if file at fpath already exists.
    If so, it increments the file"""
    if not os.path.exists(fpath):
        new_fname = fpath
    else:
        fname, file_ext = os.path.splitext(fpath)
        i = 1
        new_fname = "{}_{}{}".format(fname, i, file_ext)
        while os.path.exists(new_fname):
            i += 1
            new_fname = "{}_{}{}".format(fname, i, file_ext)
    return new_fname


def plot_data(data_file, save=True):
    "Plots the data from the csv file data_file"

    coords = np.array([])

    polaris_coords = np.array([])

    joint_set = np.array([])

    with open(data_file, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for i, row in enumerate(reader):
            joints = np.array([
                float(row["joint_{}_position".format(joint_num)])
                for joint_num in range(6)
            ])
            joint_set = np.append(joint_set, joints)
            coord = np.array([
                float(row["arm_position_x"]),
                float(row["arm_position_y"]),
                float(row["arm_position_z"])
            ])
            coords = np.append(coords, coord)
            if len(row) == 12:
                polaris = True
                polaris_coord = np.array([
                    float(row["polaris_position_x"]),
                    float(row["polaris_position_y"]),
                    float(row["polaris_position_z"]),
                ])
                polaris_coords = np.append(polaris_coords, polaris_coord)
            else:
                polaris = False

    coords = coords.reshape(-1, 3)

    if polaris:
        polaris_coords = polaris_coords.reshape(-1, 3)

    joint_set = joint_set.reshape(-1, 6)


    if polaris:
        transf, error = nmrRegistrationRigid(coords, polaris_coords)
        rot_matrix = transf.Rotation()
        translation = transf.Translation()
        polaris_coords = (polaris_coords - translation).dot(rot_matrix)
        print("Rigid Registration Error: {}".format(error))

    if not polaris:
        X, Y = np.meshgrid(
            np.arange(
                min(coords[:,0])-0.05,
                max(coords[:,0])+0.05,
                0.05
            ),
            np.arange(
                min(coords[:,1])-0.05,
                max(coords[:,1])+0.05,
                0.05
            )
        )

        (A, B, C), error = get_best_fit_plane(coords)
        Z = A*X + B*Y + C

    # plot points and fitted surface
    fig = plt.figure()
    ax = fig.gca(projection='3d')
    if polaris:
        ax.scatter(polaris_coords[:,0], polaris_coords[:,1], polaris_coords[:,2],
            c='b', s=20, label="Polaris")
        ax.scatter(coords[:,0], coords[:,1], coords[:,2], c='r', s=20, label="Arm")
    else:
        ax.plot_surface(X, Y, Z, rstride=1, cstride=1, alpha=0.2)
        ax.scatter(coords[:,0], coords[:,1], coords[:,2], c='r', s=20)

    plt.xlabel('X')
    plt.ylabel('Y')
    ax.set_zlabel('Z')
    ax.legend()
    if save:
        # Choose same filename as graph, but instead of csv, do svg
        img_filename = os.path.splitext(data_file)[0] + ".png"
        plt.savefig(img_filename)
    plt.show()


def parse_record(args):
    # pts = [
    #     PyKDL.Vector(0.06374846990290427, 0.05505725086391641, -0.15585194627277937),
    #     PyKDL.Vector(0.0530533084000882, -0.08832456079637394, -0.16132631689055202),
    #     PyKDL.Vector(-0.06385800414598963, -0.0854254024006429, -0.15375787892199785)
    # ]
    # pts = [PyKDL.Frame(Calibration.ROT_MATRIX, pt) for pt in pts]
    if args.polaris:
        from calibrate_polaris import PolarisCalibration
        calibration = PolarisCalibration(args.arm)
        joint_set = list(calibration.gen_wide_joint_positions())
        print("Starting calibration")
        time.sleep(0.5)
        calibration.record_joints(joint_set, verbose=args.verbose)
        calibration.output_to_csv()
        print("Run `./calibrate.py view {}` to view the recorded data points,"
                .format(os.path.join(calibration.folder, "polaris_point_cloud.csv")))
        print("run `./calibrate.py analyze {}` to analyze the recorded data points, or"
                .format(os.path.join(calibration.folder, "polaris_point_cloud.csv")))
        print("run `./calibrate.py analyze {} -w {}\nto analyze and write the resulting offset"
                .format(os.path.join(calibration.folder, "polaris_point_cloud.csv"), args.write))
    else:
        from calibrate_plane import PlaneCalibration

        if args.virtual:
            PlaneCalibration.run_virtual_palpations(args.virtual, show_graph=True)
        elif not args.single_palpation:
            calibration = PlaneCalibration(args.arm)
            pts = calibration.get_corners()
            goal = copy(pts[2])
            goal.p[2] += 0.10
            calibration.arm.move(goal)
            goal = copy(pts[0])
            calibration.arm.home()
            goal.p[2] += 0.090
            calibration.arm.move(goal)
            goal.p[2] -= 0.085
            calibration.arm.move(goal)
            calibration.record_points(pts, args.samples, verbose=args.verbose)
            calibration.output_to_csv()
            print("Run `./calibrate.py view {}` to view the recorded data points,"
                  .format(os.path.join(calibration.folder, "plane.csv")))
            print("run `./calibrate.py analyze {}` to analyze the recorded data points, or"
                  .format(os.path.join(calibration.folder, "plane.csv")))
            print("run `./calibrate.py analyze {} -w {}\nto analyze and write the resulting offset"
                  .format(os.path.join(calibration.folder, "plane.csv"), args.write))
        else:
            calibration = PlaneCalibration(args.arm)
            print("Position the arm at the point you want to palpate at, then press enter.",
                  end=' ')
            sys.stdin.readline()
            goal = calibration.arm.get_current_position()
            goal.p[2] += 0.05
            calibration.arm.move(goal)
            goal.p[2] -= 0.045
            calibration.arm.move(goal)
            pos_v_wrench = calibration.palpate(os.path.join(calibration.folder, "single_palpation.csv"))
            if not pos_v_wrench:
                rospy.logerr("Didn't reach surface; closing program")
                sys.exit(1)
            print("Using {}".format(calibration.analyze_palpation(pos_v_wrench, show_graph=True)))



def parse_view(args):
    # Save image to file
    if args.save:
        # Choose same filename as graph, but instead of csv, do svg
        img_filename = os.path.splitext(args.input)[0] + ".png"
    else:
        img_filename = None

    if os.path.isdir(args.input):
        # Display entire set of palpations
        from calibrate_plane import PlaneCalibration
        files = [
            os.path.join(args.input, filename)
            for filename in os.listdir(args.input)
            if filename.startswith("palpation")
        ]
        for filename in files:
            with open(filename) as csvfile:
                reader = csv.DictReader(csvfile)
                print("Reading {}".format(filename))
                pos_v_wrench = []
                for row in reader:
                    pos_v_wrench.append([
                        float(row["x-position"]),
                        float(row["y-position"]),
                        float(row["z-position"]),
                        float(row["wrench"]),
                    ])
                PlaneCalibration.analyze_palpation(pos_v_wrench, show_graph=True, img_file=img_filename)
    elif os.path.basename(args.input).startswith("palpation"):
        # Display singular palpation
        with open(args.input) as csvfile:
            reader = csv.DictReader(csvfile)
            print("Reading {}".format(filename))
            pos_v_wrench = []
            for row in reader:
                pos_v_wrench.append([
                    float(row["x-position"]),
                    float(row["y-position"]),
                    float(row["z-position"]),
                    float(row["wrench"]),
                ])
            PlaneCalibration.analyze_palpation(pos_v_wrench, show_graph=True, img_file=img_filename)
    elif os.path.basename(args.input).startswith("offset_v_error"):
        # Display offset_v_error graph

        with open(args.input) as csvfile:
            reader = csv.DictReader(csvfile)
            offset_v_error = np.array([])
            for row in reader:
                offset_v_error = np.append(
                    offset_v_error,
                    np.array([
                        float(row["offset"]),
                        float(row["error"])
                    ])
                )
            offset_v_error = offset_v_error.reshape(-1, 2)
            x = np.arange(offset_v_error[0, 0], offset_v_error[-1, 0] + 1, 1)
            equation, (min_x, min_y) = get_poly_min(offset_v_error, 2)
            y = np.zeros(x.shape)
            for e, c in enumerate(equation):
                y += c * x ** e


            # Get index of minimum of error in `offset_v_error`
            min_idx = np.where(offset_v_error[:, 1] == np.amin(offset_v_error[:, 1]))[0][0]
            # Use index to get offset, then convert from tenths of mm to mm
            actual_min = offset_v_error[min_idx, 0] / 10

            print("Minimum offset: {}mm".format(min_x / 10)) # convert from tenths of mm to mm
            print("Actual min: {}mm".format(actual_min))

            plt.plot(x, y, '-', color="blue")
            plt.scatter(offset_v_error[:, 0], offset_v_error[:, 1], s=10, color="green")
            plt.plot(min_x, min_y, 'o', color="purple")

            if args.save:
                plt.savefig(img_filename)

            plt.show()
    else:
        plot_data(args.input, save=args.save)



def parse_analyze(args):
    folder = os.path.dirname(args.input[0])
    if os.path.basename(args.input[0]) == "polaris_point_cloud.csv":
        polaris = True
    elif os.path.basename(args.input[0]) == "plane.csv":
        polaris = False
    offset_v_error_filename = os.path.join(folder, "offset_v_error.csv")

    offset_v_error = get_offset_v_error(offset_v_error_filename, args.input, polaris=polaris)
    # min_offset = get_quadratic_min(offset_v_error)
    offset_correction = offset_v_error[(np.where(offset_v_error[:, 1] == np.amin(offset_v_error[:, 1]))[0][0]), 0] / 10

    if args.write:
        if os.path.exists(args.write):
            print("Writing offset...")
            tree = ET.parse(args.write)
            root = tree.getroot()
            xpath_search_results = root.findall("./Robot/Actuator[@ActuatorID='2']/AnalogIn/VoltsToPosSI")
            if len(xpath_search_results) == 1:
                VoltsToPosSI = xpath_search_results[0]
            else:
                print("Error: There must be exactly one Actuator with ActuatorID=2")
                sys.exit(1)
            current_offset = float(VoltsToPosSI.get("Offset"))
            VoltsToPosSI.set("Offset", str(offset_correction + current_offset))
            tree.write(args.write)
            print(("Wrote offset: {}mm (Current offset) + {}mm (Offset correction) "
                   "= {}mm (Written offset)").format(current_offset, offset_correction,
                                                   offset_correction + current_offset))
        else:
            print("Error: File does not exist")
            sys.exit(1)
    else:
        print("Offset correction: {}mm".format(offset_correction))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate the dVRK")
    parser.add_argument(
        "-v", "--verbose",
        help="make output verbose", action="store_true"
    )

    subparser = parser.add_subparsers(title="subcommands")

    parser_record = subparser.add_parser(
        "record",
        help="record data for calibration"
    )
    parser_record.add_argument(
        "arm",
        help="arm to record points from"
    )
    parser_record.add_argument(
        "write",
        help="file to write to"
    )
    parser_record.add_argument(
        "-o", "--output",
        help="folder to output data",
    )
    parser_record.add_argument(
        "-v", "--virtual",
        help="run virtual palpations",
    )
    parser_record.add_argument(
        "-p", "--polaris",
        help="use polaris",
        default=False,
        action="store_true"
    )
    parser_record.add_argument(
        "-n", "--samples",
        help="number of samples per row "
        "(10 is recommended to get higher quality data)",
        default=10,
        type=int,
    )
    parser_record.add_argument(
        "-s", "--single-palpation",
        help="perform single palpation",
        action="store_true",
        default=False
    )
    parser_record.set_defaults(func=parse_record)

    parser_view = subparser.add_parser("view", help="view outputted data")
    parser_view.add_argument("input", help="data to read from")
    parser_view.set_defaults(func=parse_view)
    parser_view.add_argument(
        "--save", "-s",
        help="save to image",
        action="store_true"
    )

    parser_analyze = subparser.add_parser(
        "analyze",
        help="analyze outputted data and find offset"
    )
    parser_analyze.add_argument(
        "input",
        help="data to read from",
        nargs='+'
    )
    parser_analyze.add_argument(
        "-o", "--output",
        help="output for the graph of offset versus error "
        "(filename automatically increments)",
    )
    parser_analyze.add_argument(
        "-n", "--no-output",
        help="do not output graph of offset versus error",
        default=False,
        action="store_true"
    )
    parser_analyze.add_argument(
        "-w", "--write",
        help="write offset to file",
        default=False,
    )
    parser_analyze.set_defaults(func=parse_analyze)

    args = parser.parse_args()
    args.func(args)

