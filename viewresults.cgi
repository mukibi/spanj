#!/usr/bin/perl

use strict;
use warnings;

use DBI;

require "./conf.pl";
use Time::HiRes qw (gettimeofday tv_interval);

our ($db,$db_user,$db_pwd, $doc_root);
my $con;
my %session = ();
my $content = "";
my $adm_no = "";
my $profile = "";
my %grading = ();
my $valid = 0;
my $rank_partial = 1;
my %rank_by_points = ();
my %points = ();


my $house_label = "House/Dorm";

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/search.cgi">Search Database</a>
	<hr> 
};

my $data = "<em>Invalid adm no. provided.</em>";

if ( exists $ENV{"QUERY_STRING"} ) {
	if ( $ENV{"QUERY_STRING"} =~ /\&?adm=(\d+)\&?/ ) {	
		$adm_no = $1;
		#valid adm no.
		$data = qq!<em>Could not find the data requested. Are you sure <span style="font-weight: bolder">$adm_no</span> is a valid admission number?</em>!;
	}
}



my %student_rolls;
my %stud_data = ();
my ($table,$s_name,$o_names,$has_picture,$marks_at_adm,$rank_at_admission,$subjects,$clubs_societies,$sports_games,$responsibilities,$house_dorm);
my $exam_data = "<em>No exam records available for this student.</em>";
my $graph = "";

$con = DBI->connect("DBI:mysql:database=spanj;host=localhost;mysql_server_prepare=1", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

J: {

  if ($con) {

	#grading	
	my $prep_stmt6 = $con->prepare("SELECT id,value FROM vars WHERE id='1-grading' OR id='1-house label' OR id='1-rank partial' OR id='1-rank by points' OR id='1-points' LIMIT 5");

	if ($prep_stmt6) {

		my $rc = $prep_stmt6->execute();

		if ($rc) {

			while (	my @rslts = $prep_stmt6->fetchrow_array() ) {
			
			if ( $rslts[0] eq "1-grading" ) {
				my $grading_str = $rslts[1];
				my @grading_bts = split/,/,$grading_str;
				foreach (@grading_bts) {
					if ($_ =~ /^([^:]+):\s*(.+)$/) {
						my ($condition,$grade) = ($1,$2);
						#greater than (>|>=)
						#set min value
						if ($condition =~ /^\s*>\s*(\d+)$/) {
							${$grading{$grade}}{"min"} = $1
						}
						elsif ($condition =~ /^\s*>=\s*(\d+)$/) {
							my $min = $1;
							$min--;
							${$grading{$grade}}{"min"} = $min;
						}
						#less than (<|<=)
						#set max value of condition
						elsif ($condition =~ /^\s*<\s*(\d+)$/) {
							${$grading{$grade}}{"max"} = $1
						}
						elsif ($condition =~ /^\s*<=\s*(\d+)$/) {
							my $max = $1;
							$max++;
							${$grading{$grade}}{"max"} = $max;
						}
						#handle ranges
						#x-y
						elsif ($condition =~ /^\s*(\d+)\s*\-\s*(\d+)$/) {
							my ($min,$max) = ($1,$2);
							#don't be hard on users
							#reverse $min & $max if
							#they've been 'jumbled'
							if ($max < $min) {
								my $tmp = $max;
								$max = $min;
								$min = $tmp;
							}
							${$grading{$grade}}{"min"} = $min -1;
							${$grading{$grade}}{"max"} = $max + 1;
						}
						#handle equality (=)
						#set eqs
						elsif ($condition =~ /^\s*=\s*(\d+)$/) {
							${$grading{$grade}}{"eq"} = $1
						}
					}
				}
			}
			elsif ( $rslts[0] eq "1-house label" ) {
				if (defined $rslts[1]) {
					$house_label = htmlspecialchars($rslts[1]);
				}
			}

			elsif ($rslts[0] eq "1-rank partial") {
				if (defined $rslts[1] and lc($rslts[1]) eq "no") {
					$rank_partial = 0;
				}
			}

			elsif ( $rslts[0] eq "1-rank by points" ) {

				if ( defined($rslts[1]) and $rslts[1] =~ /^(?:[0-9]+,?)+$/ ) {
					my @yrs = split/,/,$rslts[1];
					for my $yr (@yrs) {
						$rank_by_points{$yr}++;
						#print "X-Debug-0-$yr: added '$yr' to rank_by_points\r\n";
					}
				}
			}

			elsif ($rslts[0] eq "1-points") {

				my $points_str = $rslts[1];
				my @points_bts = split/,/,$points_str;
				foreach (@points_bts) {
					if ($_ =~ /^([^:]+):\s*(.+)/) {
						my ($grade,$points) = ($1,$2);
						$points{$grade} = $points;	
					}
				}

			}

		}

		}
		else {
			print STDERR "Could not execute SELECT FROM vars statement: ", $prep_stmt6->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt6->errstr, $/;
	}
	#which tribe does s/he belong to
	my $prep_stmt0 = $con->prepare("SELECT table_name FROM adms WHERE adm_no=? LIMIT 1");
	if ($prep_stmt0) {
		my $rc = $prep_stmt0->execute($adm_no);
		if ($rc) {
			my @rslts = $prep_stmt0->fetchrow_array();
			if (@rslts) {
				$table = $rslts[0];
				$valid = 1;
				$exam_data = "";
			}
			#No such student?
			else {
				last J;
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM adms: ", $prep_stmt0->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM adms: ", $prep_stmt0->errstr, $/;	
	}
	
	my $start_year = (localtime)[5] + 1900;

	#what are the tribes around
	my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year,grad_year,size FROM student_rolls");

	if ($prep_stmt1) {
		my $rc = $prep_stmt1->execute();
		if ($rc) {
			my $current_year = (localtime)[5] + 1900;	
			while ( my @rslts = $prep_stmt1->fetchrow_array() ) {	
				#still a student
				if ($current_year <= $rslts[3]) {	
					my $class_year = 1 + ($current_year - $rslts[2]);
					$rslts[1] =~ s/\d+/$class_year/;
				}
				#graduated
				else {
					my $last_class = 1 + ($rslts[3] - $rslts[2]);
					$rslts[1] =~ s/\d+/$last_class/;
					$rslts[1] .= "(Class of $rslts[3])";
				}
				$student_rolls{$rslts[0]} = { "class" => $rslts[1], "start_year" => $rslts[2], "grad_year" => $rslts[3], "size" => $rslts[4]};	
				if ( $rslts[0] eq $table ) {
					$start_year = $rslts[2];
				}
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
	}

		
	#student records
	my $prep_stmt2 = $con->prepare("SELECT s_name,o_names,has_picture,marks_at_adm,subjects,clubs_societies,sports_games,responsibilities,house_dorm FROM `$table` WHERE adm=? LIMIT 1");
	if ($prep_stmt2) {
		my $rc = $prep_stmt2->execute($adm_no);
		if ($rc) {
			my @rslts = $prep_stmt2->fetchrow_array();
			if (@rslts) {	
				($s_name,$o_names,$has_picture,$marks_at_adm,$subjects,$clubs_societies,$sports_games,$responsibilities,$house_dorm) = @rslts;
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM $table statement: ", $prep_stmt2->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM $table statement: ", $prep_stmt2->errstr, $/;
	}

	#my %subjects;
	#for my $subj (split/,/,$subjects) {
	#	$subjects{$subj}++;
	#}
	
	#determined rank @admission	
	my %year_mates = ();
	my $grad_year = ${$student_rolls{$table}}{"grad_year"};
	my %year_mates_rolls = ();
	my $year_size = 0;
	my %subject_selection = ();

	for my $roll (keys %student_rolls) {

		next unless (${$student_rolls{$roll}}{"grad_year"} == $grad_year);
		$year_mates_rolls{$roll}++;
	
		$year_size += ${$student_rolls{$table}}{"grad_year"};

		my $prep_stmt3 = $con->prepare_cached("SELECT adm,marks_at_adm,subjects FROM `$roll`");

		if ($prep_stmt3) {
			my $rc = $prep_stmt3->execute();
			if ($rc) {
				while ( my @rslts = $prep_stmt3->fetchrow_array() ) {

					my ($adm,$marks,$subjs) = @rslts;
					if (not defined $marks or $marks eq "") {
						$marks = -1;
					}
					${$year_mates{$adm}}{"roll"} = $roll;
					${$year_mates{$adm}}{"marks"} = $marks;
					${$year_mates{$adm}}{"rank"} = "";

					my @subjects = split/,/,$subjs;

					for my $subj (@subjects) {
						$subject_selection{$adm}->{$subj}++;
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM $roll: ", $prep_stmt3->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt3->errstr, $/;
		}
	}

	

	#has_picture
	my $add_image = 0;
	my $image = "";
	if (defined $has_picture and $has_picture eq "yes") {
		opendir (my $images_dir, "${doc_root}/images/mugshots/");
		my @files = readdir ($images_dir);

		IMAGES: for my $file (@files) {
			if ($file =~ /^$adm_no\./) {
				$add_image++;
				$image = "/images/mugshots/$file";
				last IMAGES;
			}
		}
	}
		
	#rank by adm
	my $adm_rank = 0;

	for my $stud_adm ( sort { ${$year_mates{$b}}{"marks"} <=> ${$year_mates{$a}}{"marks"} } keys %year_mates ) {
		#students with no 'marks at admission will have a rank of 'N/A'
		if ( ${$year_mates{$stud_adm}}{"marks"} >= 0 ) {
			${$year_mates{$stud_adm}}{"rank"} = ++$adm_rank;
		}
	}	

	#deal with ties
	my $prev_rank = -1;
	my $prev_marks_at_adm = -1;
					
	for my $stud_5 ( sort { ${$year_mates{$a}}{"rank"} <=> ${$year_mates{$b}}{"rank"} } keys %year_mates ) {

		my $current_rank = ${$year_mates{$stud_5}}{"rank"};
		my $current_marks_at_adm = ${$year_mates{$stud_5}}{"marks"};

		#if ($prev_rank >= 0) {
			#tie
			if ($prev_marks_at_adm == $current_marks_at_adm) {
				${$year_mates{$stud_5}}{"rank"} = $prev_rank;	
			}
		#}
		$prev_rank = ${$year_mates{$stud_5}}{"rank"};
		$prev_marks_at_adm  = $current_marks_at_adm;

	}

	#create profile
	my $rowspan;
	if ($add_image) {
		$rowspan = 4;
		$rowspan++ if (defined $house_dorm and $house_dorm ne "");
		$rowspan++ if (defined $clubs_societies and $clubs_societies ne "");
		$rowspan++ if (defined $sports_games and $sports_games ne "");
		$rowspan++ if (defined $responsibilities and $responsibilities ne "");
		$rowspan += 2 if (${$year_mates{$adm_no}}{"rank"} ne "");
	}

	$profile .= qq!<p><table cellspacing="5%">!;

	

	if ($add_image) {
		use Image::Magick;
		my $magick = Image::Magick->new;

		my ($width, $height, $size, $format) = $magick->Ping("${doc_root}$image");	
				
		my $scale = 1;	
		if ($width > 120 or $height > 150) {
			my $width_scale = 120/$width;
			my $height_scale = 150/$height;

			$scale = $width_scale < $height_scale ? $width_scale : $height_scale;
		}	

		my $h = $height * $scale;
		my $w = $width * $scale;

		$profile .= qq!<tr><td rowspan="$rowspan"><a href="$image"><img height="$h" width="$w" src="$image" alt="$adm_no"></a></td>!;
	}

	

	$profile .= qq!<tr><td><span style="font-weight: bold">Adm No.: </span>$adm_no</td>!;
	$profile .= qq!<tr><td><span style="font-weight: bold">Name: </span>$s_name $o_names</td>!;
	$profile .= qq!<tr><td><span style="font-weight: bold">Class: </span>${$student_rolls{$table}}{"class"}</td>!;

	if (${$year_mates{$adm_no}}{"rank"} ne "") {
		my ($marks_at_adm, $rank_at_adm) = ("N/A", "N/A");

		if (${$year_mates{$adm_no}}{"marks"} =~ /^\d+$/) {
			$marks_at_adm = ${$year_mates{$adm_no}}{"marks"};
		}

		if (${$year_mates{$adm_no}}{"rank"} =~ /^\d+$/) {
			$rank_at_adm = ${$year_mates{$adm_no}}{"rank"};
		}

		$profile .= qq!<tr><td><span style="font-weight: bold">Marks at Admission: $marks_at_adm</span></td>!;
		$profile .= qq!<tr><td><span style="font-weight: bold">Rank at Admission: $rank_at_adm</span></td>!;
	}

	if (defined $house_dorm and $house_dorm ne "") { 
		$profile .= qq!<tr><td><span style="font-weight: bold">$house_label: </span>$house_dorm</td>!;
	}

	if (defined $clubs_societies and $clubs_societies ne "") {
		my $klubs = join( ", ", split(/,/, $clubs_societies) );
		$profile .= qq!<tr><td><span style="font-weight: bold">Clubs/Societies: </span>$klubs</td>!;
	}

	if (defined $sports_games and $sports_games ne "") {
		my $spowts = join( ", ", split(/,/, $sports_games) );
		$profile .= qq!<tr><td><span style="font-weight: bold">Sports/Games: </span>$spowts</td>!;
	}

	if (defined $responsibilities and $responsibilities ne "") {
		my $respownsibilities = join( ", ", split(/,/, $responsibilities) );
		$profile .= qq!<tr><td><span style="font-weight: bold">Responsibilities: </span>$respownsibilities</td>!;
	}

	$profile .= "</table>";
	my %exams = ();
	my %marksheets = ();

	my $num_marksheets = 0;

	my @where_clause_bts = ();
	foreach (keys %year_mates_rolls) {
		push @where_clause_bts, "roll=?";
	}
	my $where_clause = join(" OR ", @where_clause_bts);
	
	my $prep_stmt4 = $con->prepare_cached("SELECT table_name,roll,exam_name,subject,time FROM marksheets WHERE $where_clause");
	if ($prep_stmt4) {
		my $rc = $prep_stmt4->execute(keys %year_mates_rolls);
		if ($rc) {
			while ( my @rslts = $prep_stmt4->fetchrow_array() ) {
				$marksheets{$rslts[0]} = {"exam" => $rslts[2], "subject" => $rslts[3], "time" => $rslts[4]};
				$num_marksheets++;
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM marksheets: ", $prep_stmt4->errstr, $/;
		}
	}

	else {
		print STDERR "Could not prepare SELECT FROM roll statement: ", $prep_stmt4->errstr, $/;
	}

	#read exam records
	my %search_stud_records = ();
	my %all_stud_records = ();
	
	for my $marksheet (keys %marksheets) {

		my $prep_stmt5 = $con->prepare_cached("SELECT adm,marks FROM `$marksheet`");
		my $exam = ${$marksheets{$marksheet}}{"exam"};
		my $subj = ${$marksheets{$marksheet}}{"subject"};

		if ($prep_stmt5) {

			my $rc = $prep_stmt5->execute();
			if ($rc) {

				while ( my @rslts = $prep_stmt5->fetchrow_array() ) {

					next unless (defined $rslts[0] and defined $rslts[1]);
					#the student of interest
					if ($rslts[0] eq $adm_no) {
						if ( not exists $exams{$exam} ) {
							$exams{$exam} = ${$marksheets{$marksheet}}{"time"};
						}
						#the %exams hash should have the most recent 
						#(largest) time
						elsif (${$marksheets{$marksheet}}{"time"} > $exams{$exam}) {
							$exams{$exam} = ${$marksheets{$marksheet}}{"time"};
						}
						$search_stud_records{$marksheet} = $rslts[1];
					}

					if ( exists ${$all_stud_records{$rslts[0]}}{$exam} ) {

						#increment the subject count piecemeal 
						#if doing a partial rank or this subject is
						#not in the subject list
						if ( $rank_partial or not exists ${$subject_selection{$rslts[0]}}{$subj} ) {
							${${$all_stud_records{$rslts[0]}}{$exam}}{"count"}++;
						}

						${${$all_stud_records{$rslts[0]}}{$exam}}{"total"} += $rslts[1];

						my $grade = get_grade($rslts[1]);
						my $points = $points{$grade};
						${${$all_stud_records{$rslts[0]}}{$exam}}{"points_total"} += $points;					
					}

					else {
						#subject count
						if ($rank_partial) {
							${${$all_stud_records{$rslts[0]}}{$exam}}{"count"} = 1;
						}
						else {
							${${$all_stud_records{$rslts[0]}}{$exam}}{"count"} = scalar(keys %{$subject_selection{$rslts[0]}});
						}

						#total
						${${$all_stud_records{$rslts[0]}}{$exam}}{"total"} = $rslts[1];

						my $grade = get_grade($rslts[1]);
						my $points = $points{$grade};
						${${$all_stud_records{$rslts[0]}}{$exam}}{"points_total"} = $points;
					}
				}
				#calc mean score
				for my $stud_4 (keys %all_stud_records) {

					for my $exam (keys %{$all_stud_records{$stud_4}}) {

						${${$all_stud_records{$stud_4}}{$exam}}{"mean"} =  ${${$all_stud_records{$stud_4}}{$exam}}{"total"} / ${${$all_stud_records{$stud_4}}{$exam}}{"count"} if (${${$all_stud_records{$stud_4}}{$exam}}{"count"} > 0);

						${${$all_stud_records{$stud_4}}{$exam}}{"points_mean"} = ${${$all_stud_records{$stud_4}}{$exam}}{"points_total"} / ${${$all_stud_records{$stud_4}}{$exam}}{"count"} if (${${$all_stud_records{$stud_4}}{$exam}}{"count"} > 0);

					}
				} 
			}
			else {
				print STDERR "Could not execute SELECT FROM $marksheet statement: ", $prep_stmt5->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM $marksheet statement: ", $prep_stmt5->errstr, $/;
		}
	}

	#determine overall rank
	#all this code can probably be replaced
	#with a  neat subroutine
	#TODO

	for my $exam_n_1 (keys %exams) {

		my %student_data = ();
		#ranking
		my %class_rank_cntr = ();

		foreach (keys %student_rolls) {
			$class_rank_cntr{$_} = 0;
		}
		my $overall_cntr = 0;

		my $sort_by = "mean";

		my $exam_yr = (localtime $exams{$exam_n_1})[5] + 1900;
		my $stud_yr = ($exam_yr - $start_year) + 1;

		if ( exists $rank_by_points{$stud_yr} ) {
			$sort_by = "points_mean";
		}


		#if (exists $rank_by_points{$ex
		#
		for my $stud_rec ( keys %all_stud_records ) {
			if ( exists ${$all_stud_records{$stud_rec}}{$exam_n_1} ) {
				$student_data{$stud_rec} = ${${$all_stud_records{$stud_rec}}{$exam_n_1}}{$sort_by};
			}
		}

		my $cntr = 0;

		for my $stud ( sort { $student_data{$b} <=> $student_data{$a} } keys %student_data ) {

			my $roll = ${$year_mates{$stud}}{"roll"};
		
			my $f_cntr = sprintf("%03d", $cntr++);
			my $num_subjs = scalar(keys %{$subject_selection{$stud}});

			print qq!X-Debug-$f_cntr: pos->$f_cntr; points->$student_data{$stud}; stud->$stud; total points->${${$all_stud_records{$stud}}{$exam_n_1}}{"points_total"}; num_subjects->$num_subjs\r\n! if ($exam_n_1 eq "Term Average TERM 1(2014)");

 			${${$all_stud_records{$stud}}{$exam_n_1}}{"overall_rank"} = ++$overall_cntr;
			${${$all_stud_records{$stud}}{$exam_n_1}}{"class_rank"} = ++$class_rank_cntr{$roll}; 	
		}
	}

	
	
	#deal with ties in overall_rank
	for my $exam_n_2 (keys %exams) {

		my $sort_by = "mean";

		my $exam_yr = (localtime $exams{$exam_n_2})[5] + 1900;
		my $stud_yr = ($exam_yr - $start_year) + 1;

		if ( exists $rank_by_points{$stud_yr} ) {
			$sort_by = "points_mean";
		}


		$prev_rank = -1;
		my $prev_avg = -1;

		my %student_data = ();
		for my $stud_rec ( keys %all_stud_records ) {
			if ( exists ${$all_stud_records{$stud_rec}}{$exam_n_2} ) {
				$student_data{$stud_rec} = ${${$all_stud_records{$stud_rec}}{$exam_n_2}}{$sort_by};
			}
		}
		for my $stud_2 (sort { $student_data{$a} <=> $student_data{$b} } keys %student_data) {
			my $current_rank = ${${$all_stud_records{$stud_2}}{$exam_n_2}}{"overall_rank"};
			my $current_avg  = ${${$all_stud_records{$stud_2}}{$exam_n_2}}{$sort_by};

			#if ($prev_rank >= 0) {
				#tie
				if ($prev_avg == $current_avg) {
					${${$all_stud_records{$stud_2}}{$exam_n_2}}{"overall_rank"} = $prev_rank;	
				}
			#}
			$prev_rank = ${${$all_stud_records{$stud_2}}{$exam_n_2}}{"overall_rank"};
			$prev_avg  = $current_avg;
		}
	}	
	
	for my $exam_n_3 (keys %exams) {

		my $sort_by = "mean";

		my $exam_yr = (localtime $exams{$exam_n_3})[5] + 1900;
		my $stud_yr = ($exam_yr - $start_year) + 1;

		if ( exists $rank_by_points{$stud_yr} ) {
			$sort_by = "points_mean";
		}


		#handle ties in class_rank 
		my %class_rank_cursor = ();

		foreach ( keys %student_rolls ) {	
			$class_rank_cursor{$_} = {"prev_rank" => -1, "prev_avg" => -1};
		}

		my %student_data = ();

		for my $stud_rec ( keys %all_stud_records ) {
			if ( exists ${$all_stud_records{$stud_rec}}{$exam_n_3} ) {
				${$student_data{$stud_rec}}{$sort_by} = ${${$all_stud_records{$stud_rec}}{$exam_n_3}}{$sort_by};
				${$student_data{$stud_rec}}{"class_rank"} = ${${$all_stud_records{$stud_rec}}{$exam_n_3}}{"class_rank"};
				${$student_data{$stud_rec}}{"overall_rank"} = ${${$all_stud_records{$stud_rec}}{$exam_n_3}}{"overall_rank"};
			}
		}

		for my $stud_3 (sort { ${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {

			my $roll = ${$year_mates{$stud_3}}{"roll"};
				
			my $current_rank = ${$student_data{$stud_3}}{"class_rank"};
			my $current_avg = ${$student_data{$stud_3}}{$sort_by};
							
		#	if (${$class_rank_cursor{$roll}}{"prev_rank"} >= 0) {
			#tie
			if (${$class_rank_cursor{$roll}}{"prev_avg"} == $current_avg) {
				${${$all_stud_records{$stud_3}}{$exam_n_3}}{"class_rank"} = ${$class_rank_cursor{$roll}}{"prev_rank"};	
			}
		#	}
			${$class_rank_cursor{$roll}}{"prev_rank"} = ${${$all_stud_records{$stud_3}}{$exam_n_3}}{"class_rank"};
			${$class_rank_cursor{$roll}}{"prev_avg"}  = $current_avg;
		}
	}
	
	my @subjects_list = ();
	if (defined $subjects) {
		@subjects_list =  split/,/, $subjects;
	}

	my $do_grading = 0;
	$do_grading++ if (keys %grading);

	#add exam data
	#without position
	for my $exam (sort { $exams{$a} <=> $exams{$b} } keys %exams) {

		my %subjects_hash = ();
		foreach (@subjects_list) {
			#feel very clever abt this
			#helps with dealing with 
			#case-insensitivity
			$subjects_hash{lc($_)} = $_; 
		}
		$exam_data .= qq!<h3 style="text-decoration: underline">$exam</h3>!;
		$exam_data .= qq!<p><table border="1" cellspacing="5%">!;

		if ($do_grading) {
			$exam_data .= "<thead><th>Subject<th>Score<th>Grade</thead><tbody>"
		}
		else {
			$exam_data .= "<thead><th>Subject<th>Score</thead><tbody>"
		}
		for my $marksheet (sort { ${$marksheets{$a}}{"subject"} cmp ${$marksheets{$b}}{"subject"} } keys %search_stud_records) {
			next unless (${$marksheets{$marksheet}}{"exam"} eq $exam);
			my $subject = ${$marksheets{$marksheet}}{"subject"};
			my $score = 0;

			if (exists $search_stud_records{$marksheet}) {
				$score = $search_stud_records{$marksheet};
			}

			$exam_data .= qq!<tr><td><span style="font-weight: bold">$subject</span><td>$score!;	
			if ($do_grading) {
				my $grade = get_grade($score);
				$exam_data .= "<td>$grade";
			}
			delete $subjects_hash{lc($subject)};
		}
		#Add N/A Subjects
		for my $null_subject (keys %subjects_hash) {
			$exam_data .= qq!<tr><td><span style="font-weight: bold">$subjects_hash{$null_subject}</span><td>N/A!;	
			if ($do_grading) {
				$exam_data .= "<td>N/A";
			}
		}
		#Add Grades
		my $colspan = 1;
		my $mean_score = sprintf ("%.3f", ${${$all_stud_records{$adm_no}}{$exam}}{"mean"} );
		if ($do_grading) {	
			my $mean_grade = get_grade($mean_score);
			$exam_data .= qq!<tr><td><span style="font-weight: bold">Mean Score</span><td>$mean_score<td>$mean_grade!;
		}
		else {
			$exam_data .= qq!<tr><td><span style="font-weight: bold">Mean Score</span><td colspan="$colspan">$mean_score!;
		}

		#Positions
		my $class_size = ${$student_rolls{$table}}{"size"};
		my $overall_size = 0;
		foreach (keys %student_rolls) {
			if (${$student_rolls{$_}}{"grad_year"} == ${$student_rolls{$table}}{"grad_year"}) {
				$overall_size += ${$student_rolls{$_}}{"size"};
			}
		}
		my ($class_rank,$overall_rank) = (qq!<span style="font-weight: bold">N/A</span>!, qq!<span style="font-weight: bold">N/A</span>!);

		if ( exists ${${$all_stud_records{$adm_no}}{$exam}}{"class_rank"} ) {
			$class_rank = qq!<span style="font-weight: bold">${${$all_stud_records{$adm_no}}{$exam}}{"class_rank"}</span> out of $class_size!;
		}

		if ( exists ${${$all_stud_records{$adm_no}}{$exam}}{"overall_rank"} ) {
			$overall_rank = qq!<span style="font-weight: bold">${${$all_stud_records{$adm_no}}{$exam}}{"overall_rank"}</span> out of $overall_size!;
		}

		if ($do_grading) {
			$exam_data .= qq!<tr><td><span style="font-weight: bold">Class Rank</span><td colspan="2">$class_rank!;
			$exam_data .= qq!<tr><td><span style="font-weight: bold">Overall Rank</span><td colspan="2">$overall_rank!;
		}
		else {
			$exam_data .= qq!<tr><td><span style="font-weight: bold">Class Rank</span><td>$class_rank!;
			$exam_data .= qq!<tr><td><span style="font-weight: bold">Overall Rank</span><td>$overall_rank!;
		}
		$exam_data .= "<tbody></table>";

	}

	

	#add class/overall posi graph
	#add mean score
	my ($min_rank, $max_rank, $min_mean, $max_mean) = (undef, undef, undef, undef);
	my (@exam_list, @overall_rank, @class_rank, @mean_score);

	for my $exam_n_4 (sort { $exams{$a} <=> $exams{$b} } keys %exams) {
		push @exam_list, qq!"$exam_n_4"!;
		my ($overall_rank, $class_rank, $mean_score) = (${${$all_stud_records{$adm_no}}{$exam_n_4}}{"overall_rank"}, ${${$all_stud_records{$adm_no}}{$exam_n_4}}{"class_rank"}, ${${$all_stud_records{$adm_no}}{$exam_n_4}}{"mean"});

		push @overall_rank,$overall_rank;
		push @class_rank,$class_rank;
		push @mean_score, $mean_score;

		#set the min and max ranks as the 1st
		#values of class and overall ranks seen (respectively)
		if ( not defined($min_rank) ) {
			$min_rank = $class_rank;
			$max_rank = $overall_rank;
		}
		else {
			$max_rank = $overall_rank if ($overall_rank > $max_rank);
			$min_rank = $class_rank if ($class_rank < $min_rank);
		}

		#set the min and max means as the 1st
		#mean score seen
		if ( not defined($min_mean) ) {
			$min_mean = $max_mean = int($mean_score);
		}
	
		else {
			$max_mean = int($mean_score) if ($mean_score > $max_mean);
			$min_mean = int($mean_score) if ($mean_score < $min_mean);
		}
	}

	#plot within 5 positions of the min & max vals. 
	#largely pointless--R is kind enough to clip the plot
	$min_rank -= 5;
	$min_rank = 1 if ($min_rank < 1);
	$max_rank += 5;

	$min_mean -= 5;
	$min_mean = 0 if ($min_mean < 0);
	$max_mean += 5;

	my $last_exam_index = scalar(@exam_list) - 1;

	if (@overall_rank) {
		my $mean_gnuplot_data = "";
		my ($position_overall_gnuplot_data, $position_class_gnuplot_data) = ("", "");

		my @xtics = ();
		my $current_year = "";
		for (my $i = 0; $i < @exam_list; $i++) {

			$mean_gnuplot_data .= "$i $mean_score[$i]\n";
			$position_overall_gnuplot_data .= "$i $overall_rank[$i]\n";
			$position_class_gnuplot_data .= "$i $class_rank[$i]\n";

			if ($exam_list[$i] =~ /(\d{4})/) {
				my $yr = $1;
				#add to xtics
				if ($yr ne $current_year) {
					push @xtics, qq%'$yr' $i%;
					$current_year = $yr;
				}
				else {
					push @xtics, qq%'' $i%;
				}
			}
		}

		$mean_gnuplot_data .= "e\n";
		$position_overall_gnuplot_data .= "e\n";
		$position_class_gnuplot_data .= "e\n";

		my $set_x_tics = "";
		if (@xtics) {
			$set_x_tics = "set xtics (" . join(", ", @xtics) . ");\\";
		}
	
		my $id = int(rand 100);

		my $mean_gnuplot_code =
qq%set terminal png size 700,700;\\
set output '${doc_root}/images/graphs/$adm_no-mean.png';\\
set datafile separator whitespace;\\
set title 'Student\\`s Progress(Mean Score)  ';\\
set xlabel 'Year';\\
set ylabel 'Mean Score';\\
set xrange [0:$last_exam_index];\\
set yrange [$min_mean:$max_mean];\\
set grid ytics;\\
set grid xtics;\\
set tmargin 2;\\
set rmargin 3;\\
$set_x_tics
plot '-' using 1:2 notitle with linespoints linecolor rgb '#FF0000' linewidth 3;\\
%;

		$id = int(rand 100);

		my $position_gnuplot_code =
qq%set terminal png size 700,700;\\
set output '${doc_root}/images/graphs/$adm_no-rank.png';\\
set multiplot;\\
set title 'Student\\`s Progress(Rank)  ';\\
set xlabel 'Year';\\
set ylabel 'Position';\\
set xrange [0:$last_exam_index];\\
set yrange [$min_rank:$max_rank];\\
set grid ytics;\\
set tmargin at screen 0.9;\\
set bmargin at screen 0.1;\\
set rmargin at screen 0.98;\\
set lmargin at screen 0.15;\\
$set_x_tics
plot '-' using 1:2 notitle with linespoints linecolor rgb '#FF0000' linewidth 3;\\
unset ylabel;\\
unset xlabel;\\
unset ytics;\\
unset xtics;\\
unset title;\\
plot '-' using 1:2 notitle with linespoints linecolor rgb '#00FF00' linewidth 3;\\
unset multiplot;\\
%;
		
		my @color_palette = ("#000000","#0000FF","#A52A2A","#7FFF00","#FFD700","#00FF00","#FF00FF","#6B8E23","#FFA500","#A020F0","#FF0000","#A0522D","#00FFFF","#FF7F50","#B03060","#7FFFD4","#D2691E","#B22222","#000080","#DA70D6","#FA8072","#FF6347","#40E0D0","#EE82EE","#FFFF00","#CD853F");
 	
		my @exam_indeces = 0..$last_exam_index;
	
		
		#add plot for each subject
		my %subject_scores = ();
		my %missing_data = ();
		my @missing_data_str = ();

		my $num_of_exams = scalar(keys %exams);
		my $exam_cntr = 0;

		#default mark is 0
		foreach (@subjects_list) {
			$subject_scores{lc($_)} = [];
			for (my $i = 0; $i < $num_of_exams; $i++) {
				push @{$subject_scores{lc($_)}}, 0;
			}
		}

		my ($min_score,$max_score) = (undef,undef);
		for my $exam ( sort { $exams{$a} <=> $exams{$b} } keys %exams ) {

			my %subjects_hash = ();
			foreach (@subjects_list) {
				#feel very clever abt this
				#helps with dealing with 
				#case-insensitivity
				$subjects_hash{lc($_)} = $_;
			}

			#nothing insensitive about guaranteeing case-insensitivity
			for my $marksheet ( keys %search_stud_records ) {
				next unless (${$marksheets{$marksheet}}{"exam"} eq $exam);
	
				my $subject = lc(${$marksheets{$marksheet}}{"subject"});
				my $score = $search_stud_records{$marksheet};

				if (not defined $min_score) {
					$min_score = $score;
					$max_score = $score;
				}
				else {
					$min_score = $score if ($score < $min_score);
					$max_score = $score if ($score > $max_score);
				}

				${$subject_scores{$subject}}[$exam_cntr] = $score;
				delete $subjects_hash{$subject};
			}

			#record missing marks as so
			for my $missing_subject (keys %subjects_hash) {
				if ( not exists $missing_data{$missing_subject} ) {
					$missing_data{$missing_subject} = [];	
				}
				push @{$missing_data{$missing_subject}}, $exam_cntr;
				push @missing_data_str, $exam . " " . $subjects_hash{$missing_subject};	
				${$subject_scores{$missing_subject}}[$exam_cntr] = 0;
			}

			#if there is a missing subject, set min_score to 0
			if (keys %missing_data) {
				$min_score = 0;
			}
			$exam_cntr++;
		}
		$min_score -= 5;
		$min_score = 0 if ($min_score <= 0);

		$max_score += 5;

		my $subjects_gnuplot_data = "";
		my $subjects_gnuplot_code =
qq%set terminal png size 1000,1000;\\
set output '${doc_root}/images/graphs/$adm_no-subjects.png';\\
set multiplot;\\
set title 'Student\\`s Progress(All Subjects)  ';\\
set xlabel 'Year';\\
set ylabel 'Score';\\
set xrange [0:$last_exam_index];\\
set yrange [$min_score:$max_score];\\
set ytics;\\
set grid ytics;\\
set tmargin at screen 0.9;\\
set bmargin at screen 0.1;\\
set rmargin at screen 0.98;\\
set lmargin at screen 0.08;\\
$set_x_tics
%;
		#plot each subjects lines
		#watch out for exhausing the color palette
		my $color_cntr = 0;
		for my $subj (keys %subject_scores) {	
			my @progress = @{$subject_scores{$subj}};	
			
			my @exam_indeces = 0..$#progress;	

			for (my $i = 0; $i < @progress; $i++) {
				if (not defined $progress[$i]) {	
					$progress[$i] = 0;
				}		
			}

			for (my $i = 0; $i < @progress; $i++) {
				$subjects_gnuplot_data .= "$i $progress[$i]\n"
			}

			$subjects_gnuplot_data .= "e\n";
			$subjects_gnuplot_code .= 
qq%plot '-' using 1:2 notitle with linespoints linecolor rgb '$color_palette[$color_cntr]' linewidth 3;\\
%;
			
			if ($color_cntr == 0) {
				$subjects_gnuplot_code .=
qq%unset ylabel;\\
unset xlabel;\\
unset ytics;\\
unset xtics;\\
unset title;\\
%;
			}
	
			
			#label missing data
			if (exists ($missing_data{$subj})) {
				my @missing = @{$missing_data{$subj}};
				for my $missing_exam_index (@missing) {	
					$subjects_gnuplot_code .= 

qq%set label '*' at first $missing_exam_index,0;\\
%;
					
					

	
				}
			}
			
			#recycle colors
			#this will create utter chaos
			#but if the user needs more than 25
			#lines on their graph, they probably expect(deserve?) chaos
			$color_cntr = 0 if (++$color_cntr >= @color_palette);
		}
		#$subjects_plot_r_code .= "dev.off();";
	
		#plot meanscore
		#`echo '$mean_gnuplot_data' | $mean_gnuplot_code`;
		#plot overall/class ranks
		#`echo '$position_class_gnuplot_data$position_overall_gnuplot_data' | $position_gnuplot_code`;

		`echo '${mean_gnuplot_data}${position_class_gnuplot_data}${position_overall_gnuplot_data}${subjects_gnuplot_data}' | gnuplot -e "${mean_gnuplot_code}${position_gnuplot_code}${subjects_gnuplot_code}"`;

		

		#throw away stdout,stderr
		#open(my $rscript, "|Rscript 2>/dev/null 1>/dev/null --no-init-file --no-site-file --default-packages=base,graphics,grDevices -") or print STDERR "Could not open pipe to Rscript$/";
		#can open pipe?
		#if ($rscript) {
			#print $rscript $r_code;
			#close $rscript;
		
			#graph has been created?
			if (-e "${doc_root}/images/graphs/$adm_no-rank.png") {
				$graph .= 
qq!
<p>
<h3 style="text-decoration: underline">Student's Progress(Class & Overall Ranks)</h3>
<TABLE border="1">
<TR>
<TD><a href="/images/graphs/$adm_no-rank.png"><img src="/images/graphs/$adm_no-rank.png" alt="Student&#x27s Progress(Class & Overall Ranks)" title="Student&#x27s Progress(Class & Overall Ranks); Remember: A falling graph indicates improvement(because a smaller rank is better)"></a>
<TD style="vertical-align: middle"><SPAN style="color: green">Overall rank</SPAN><BR><SPAN style="color: red">Class Rank</SPAN>
</TABLE>
!;
			}
			else {
				print STDERR "Rank graph was not created by R$/";
			}
		
			if (-e "${doc_root}/images/graphs/$adm_no-mean.png") {
				$graph .=
qq!
<p>
<h3 style="text-decoration: underline">Student's Progress(Mean score)</h3>
<table border="1">
<td><a href="/images/graphs/$adm_no-mean.png"><img src="/images/graphs/$adm_no-mean.png" alt="Student%27s Progress(Mean score)" title="Student&#x27s Progress(Mean score)"></a>
<TD style="vertical-align: middle"><SPAN style="color: red">Mean score</SPAN>
</table>
!;
			}
			else {
				print STDERR "Mean score graph was not created by R$/";
			}

			if (-e  "${doc_root}/images/graphs/$adm_no-subjects.png") {
				$graph .=
qq!
<p>
<h3 style="text-decoration: underline">Student's Progress(All subjects)</h3>
<table border="1">
<td><a href="/images/graphs/$adm_no-subjects.png"><img src="/images/graphs/$adm_no-subjects.png" alt="Student%27s Progress(All subjects)" title="Student&#x27s Progress(All subjects)"></a>
<td style="vertical-align: middle">
!;
				#add legend
				#1st subjects
				my %subject_names;
				foreach (@subjects_list) {
					$subject_names{lc($_)} = $_;
				}
				my $color_cntr = 0;
				for my $subj (keys %subject_scores) {
				
				#for my $subj (sort {$a cmp $b} keys %subject_scores) {
					my $color = $color_palette[$color_cntr];
					my $subject = "";
					if (exists $subject_names{$subj}) {
						$subject = $subject_names{$subj};
					}
					else {				
						$subject = "*";
						map { $subject .= " " . ucfirst($_) } split/\s+/, $subj;
					}

					$graph .= qq!<span style="color: $color">$subject</span><br>!;
					$color_cntr = 0 if (++$color_cntr >= @color_palette);
				}
				#next missing subjects (if any)
				if (@missing_data_str) {
					$graph .= "<em>* Data missing</em> (" . join(", ", @missing_data_str) . ")";
				}
				$graph .= "</table>";
			}
			else {
				print STDERR "Subjects graph was not created by R$/";
			}
		}
	#}
	
  }
}
	if ($valid) { 
		$data = qq!<p>$profile<p>$exam_data<p>$graph!;
	}
	$content =
qq*
<!DOCTYPE html>
<HTML lang="en">
<HEAD>
<META http-equiv="Content-Type" content="text/html; charset=ISO-8859-1">
<TITLE>Spanj :: Exam Management Information System :: Search Database</TITLE>
</HEAD>
<BODY>
$header
$data
</BODY>
</HTML>
*;

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";
print "\r\n";
print $content;
$con->disconnect();



sub grade_sort {
	#idea is to try & give the student
	#the best grade their marks can
	#earn. Presumably, higher marks == better grade

		
	#both have a minimum
	#use the higher of the 2
	if (exists ${$grading{$a}}{"min"} and exists ${$grading{$b}}{"min"}) {
		return ${$grading{$b}}{"min"} <=> ${$grading{$a}}{"min"};
	}
	#both have a maximum
	#use the higher of the 2
	elsif (exists ${$grading{$a}}{"max"} and exists ${$grading{$b}}{"max"}) {
		return ${$grading{$b}}{"max"} <=> ${$grading{$a}}{"max"};
	}
	elsif (exists ${$grading{$a}}{"eq"} and exists ${$grading{$b}}{"eq"}) {
		return ${$grading{$b}}{"eq"} <=> ${$grading{$a}}{"eq"};
	}
	#$a has eq, $b doesn't 
	if (exists ${$grading{$a}}{"eq"}) {
		return 1;
	}
	#$b has eq, $a doesn't
	else {
		return -1;
	}  

	#$a has a min set, $b doesn't 
	if (exists ${$grading{$a}}{"min"}) {
		return 1;
	}
	#$b has a min set, $a doesn't
	else {
		return -1;
	}
}

sub get_grade {
	my $grade = "";
	return "" unless (@_);
	my $score = $_[0];

	GRADE: for my $tst_grade (sort grade_sort keys %grading) {
		my %tst_conds = %{$grading{$tst_grade}};
		#check equality
		if (exists $tst_conds{"eq"}) {
			if ($score == $tst_conds{"eq"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
		elsif (exists $tst_conds{"min"}) {
			if ($score > $tst_conds{"min"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
		elsif (exists $tst_conds{"max"}) {
			if ($score < $tst_conds{"max"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
	}
	return $grade;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}
