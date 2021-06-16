import os
import pandas as pd
import numpy as np
from pathlib import Path
from joint_parser import J_LISTTYPE_COLUMNS
from cache import TransposeKey
from common import (
    DATASETDIR,
    SYNTHDATASETDIR,
    DATASETSUMMARYFILE,
)
from feature_representation import KEYS, INTERVALCLASSES
from input_representations import available_representations as availableInputs
from output_representations import (
    available_representations as availableOutputs,
)
from argparse import ArgumentParser


def _padToSequenceLength(arr, sequenceLength):
    frames, features = arr.shape
    featuresPerSequence = sequenceLength * features
    featuresInExample = frames * features
    padding = featuresPerSequence - (featuresInExample % featuresPerSequence)
    arr = np.pad(arr.reshape(-1), (0, padding))
    arr = arr.reshape(-1, sequenceLength, features)
    return arr


def _getTranspositions(df):
    localKeys = df.a_localKey.to_list()
    localKeys = set(localKeys)
    ret = []
    for interval in INTERVALCLASSES:
        if interval == "P1":
            continue
        transposed = [TransposeKey(k, interval) for k in localKeys]
        # Transpose to this interval if every modulation lies within
        # the set of KEY classes that we can classify
        if set(transposed).issubset(set(KEYS)):
            ret.append(interval)
    return ret


def generateDataset(
    synthetic=False,
    dataAugmentation=False,
    collections=["abc", "bps", "haydnop20", "wir", "tavern"],
    testCollections=["abc", "bps", "haydnop20", "wir", "tavern"],
    inputRepresentations=["BassChromagram38"],
    outputRepresentations=[
        "LocalKey35",
        "PrimaryDegree22",
        "SecondaryDegree22",
        "ChordQuality15",
        "Inversion4",
        "ChordRoot35",
    ],
    sequenceLength=640,
    scrutinizeData=True,
    testSetOn=False,
):
    outputArrays = {}
    for split in ["training", "validation"]:
        for x in inputRepresentations:
            outputArrays[split + f"_X_{x}"] = []
        for y in outputRepresentations:
            outputArrays[split + f"_y_{y}"] = []
    training = ["training", "validation"] if testSetOn else ["training"]
    validation = ["test"] if testSetOn else ["validation"]
    datasetDir = DATASETDIR if not synthetic else SYNTHDATASETDIR
    summaryFile = os.path.join(datasetDir, DATASETSUMMARYFILE)
    if not os.path.exists(summaryFile):
        print("You need to generate the tsv files first.")
        exit()
    datasetSummary = pd.read_csv(summaryFile, sep="\t")
    trainingdf = datasetSummary[
        (datasetSummary.collection.isin(collections))
        & (datasetSummary.split.isin(training))
    ]
    validationdf = datasetSummary[
        (datasetSummary.collection.isin(testCollections))
        & (datasetSummary.split.isin(validation))
    ]
    df = pd.concat([trainingdf, validationdf])
    for row in df.itertuples():
        split = row.split
        if testSetOn:
            if split == "validation":
                split = "training"
            elif split == "test":
                split = "validation"
        else:
            if split == "test":
                continue
        print(f"{row.split} -used-as-> {split}", row.file)
        tsvlocation = os.path.join(datasetDir, row.split, row.file)
        df = pd.read_csv(tsvlocation + ".tsv", sep="\t")
        for col in J_LISTTYPE_COLUMNS:
            df[col] = df[col].apply(eval)
        # Filter the bad quality annotations
        if scrutinizeData and split == "training":
            originalIndex = len(df.index)
            df = df[
                (df.qualitySquaredSum < 0.75)
                & (df.measureMisalignment == False)
                & (df.incongruentBass < 0.8)
            ]
            filteredIndex = len(df.index)
            print(f"\t({originalIndex}, {filteredIndex})")
        for inputRepresentation in inputRepresentations:
            inputLayer = availableInputs[inputRepresentation](df)
            Xi = inputLayer.array
            Xi = _padToSequenceLength(Xi, sequenceLength)
            if dataAugmentation and split == "training":
                transpositions = _getTranspositions(df)
                print("\t", transpositions)
                for transposition in inputLayer.dataAugmentation(
                    transpositions
                ):
                    Xi = np.concatenate(
                        (
                            Xi,
                            _padToSequenceLength(
                                transposition, sequenceLength
                            ),
                        )
                    )
            npzfile = f"{split}_X_{inputRepresentation}"
            for sequence in Xi:
                outputArrays[npzfile].append(sequence)
        for outputRepresentation in outputRepresentations:
            outputLayer = availableOutputs[outputRepresentation](df)
            yi = outputLayer.array
            yi = _padToSequenceLength(yi, sequenceLength)
            if dataAugmentation and split == "training":
                for tr in outputLayer.dataAugmentation(transpositions):
                    yi = np.concatenate(
                        (
                            yi,
                            _padToSequenceLength(tr, sequenceLength),
                        )
                    )

            npzfile = f"{split}_y_{outputRepresentation}"
            for sequence in yi:
                outputArrays[npzfile].append(sequence)
    np.savez_compressed(datasetDir, **outputArrays)


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Generate pkl files for every tsv training example."
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Search for a synthetic dataset, not one from real scores.",
    )
    parser.add_argument(
        "--dataAugmentation",
        action="store_true",
        help="Perform data augmentation on the training set.",
    )
    parser.add_argument(
        "--collections",
        choices=["abc", "bps", "haydnop20", "wir", "wirwtc", "tavern"],
        default=["abc", "bps", "haydnop20", "wir", "wirwtc", "tavern"],
        nargs="+",
        help="Include training files from a specific corpus/collection.",
    )
    parser.add_argument(
        "--test_collections",
        choices=["abc", "bps", "haydnop20", "wir", "wirwtc", "tavern"],
        default=["abc", "bps", "haydnop20", "wir", "wirwtc", "tavern"],
        nargs="+",
        help="Include test files from a specific corpus/collection.",
    )
    parser.add_argument(
        "--input_representations",
        nargs="+",
        default=["BassChromagram38"],
        choices=list(availableInputs.keys()),
    )
    parser.add_argument(
        "--output_representations",
        nargs="+",
        default=[
            "LocalKey35",
            "PrimaryDegree22",
            "SecondaryDegree22",
            "ChordQuality15",
            "Inversion4",
            "ChordRoot35",
        ],
        choices=list(availableOutputs.keys()),
    )
    parser.add_argument(
        "--sequence_length",
        type=int,
        default=640,
        choices=range(64, 640),
    )
    parser.add_argument(
        "--scrutinize_data",
        action="store_true",
        default=False,
        help="Exclude bad-quality annotations from the training data.",
    )
    parser.add_argument(
        "--test_set_on",
        action="store_true",
        default=False,
        help="Use the real test set, and add the validation set to training.",
    )
    args = parser.parse_args()
    generateDataset(
        synthetic=args.synthetic,
        dataAugmentation=args.dataAugmentation,
        collections=args.collections,
        testCollections=args.test_collections,
        inputRepresentations=args.input_representations,
        outputRepresentations=args.output_representations,
        sequenceLength=args.sequence_length,
        testSetOn=args.test_set_on,
        scrutinizeData=args.scrutinize_data,
    )
