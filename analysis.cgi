#!/usr/bin/perl

use strict;
use warnings;
use DBI;
use Digest::SHA qw/sha1_hex/;

require  "./conf.pl";

my $content = "";
our ($db,$db_user,$db_pwd,$doc_root);
my %session;
my $update_session = 0;
my $con;

#should I use a ref here
#thus scoped to make them accessible to return_ordered()
my %matching_adms = ();
my $group_by;
#and get_grade()
my %grading = ();
my %points = ();
my %points_to_grade = ();

my %sign_strength = ("+" => 1, "_" => 2, "-" => 3);

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/analysis.cgi">Run Analysis</a>
	<hr> 
};

my $stage = 1;
my $spc = " ";
#load up the session data 
if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/\+/$spc/ge;
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/\+/$spc/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
}

my %auth_params;

if (exists $ENV{"REQUEST_METHOD"}) {
	if(uc($ENV{"REQUEST_METHOD"}) ne "POST") {
		$stage = 1;
		$session{"stage"} = 1;	
	}
	else {
		my $str = "";

		while (<STDIN>) {
			$str .= $_;
		}
			
		my $prev_analysis_id = "";
		if (exists $session{"analysis_id"}) {
			$prev_analysis_id = $session{"analysis_id"};
		}
		my $analysis_id_fodder = $str . $prev_analysis_id;
		my $analysis_id = uc(sha1_hex($analysis_id_fodder));
		$session{"analysis_id"} = $analysis_id;

		$update_session++;
		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;
		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
				$k =~ s/\+/ /g;
				$v =~ s/\+/ /g;
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
		#user has just told us what sought of
		#analysis and on who they want to perform
		if ($session{"stage"} == 1) {	
			$session{"stage"} = 2;
			$stage = 2;
			$update_session++;
		}
		else {
			if (exists $session{"stage"}) {	
				$stage = $session{"stage"};
			}
		}
	}
}

$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError' => 1, 'AutoCommit' =>  0});

my @errors = ();
my %marksheets = ();
my %exam_seq = ();

K: {
	if ($stage == 3) {
		#determine dataset

		#what student rolls are there?
		my %classes;
		my $current_yr = (localtime)[5] + 1900;

		my $prep_stmt_3_0 = $con->prepare("SELECT table_name,class,start_year,grad_year FROM student_rolls");

		if ($prep_stmt_3_0) {
			my $rc = $prep_stmt_3_0->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt_3_0->fetchrow_array()) {
					my ($stud_roll,$class,$start_year,$grad_year) = @rslts;	
					$classes{$stud_roll} = {"class" => $class, "start_year" => $start_year, "grad_year" => $grad_year};
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt_3_0->errstr,$/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt_3_0->errstr, $/;
		}
	
		#is there any class lim?
		if (exists $session{"classes"}) {
			my @classes = split/,/, lc($session{"classes"});	
			my %wanted_classes = ();
			@wanted_classes{@classes} = @classes;
			for my $roll (keys %classes) {
				my ($class, $start, $grad) = ( ${$classes{$roll}}{"class"}, ${$classes{$roll}}{"start_year"}, ${$classes{$roll}}{"grad_year"} );
				my $match = 0;
				my $yr;	
				H: for (my $i = $start; $i <= $grad; $i++) { 

					$yr = ($i - $start) + 1;
					$class =~ s/\d+/$yr/;
					${$classes{$roll}}{"class"} = $class;
					my $reformd_class = lc($class . "(" . $grad . ")");	
					if (exists $wanted_classes{$reformd_class}) {	
						$match++;	
						${$classes{$roll}}{"year"} = $i;	
						last H;
					}
				}
				unless ($match) {	
					delete $classes{$roll};	
				}
			}
		}
		#only use current students
		else {	
			for my $class (keys %classes) {
				unless ($current_yr <= ${$classes{$class}}{"grad_year"} and $current_yr >= ${$classes{$class}}{"start_year"}) {
					delete $classes{$class};					
				}
				else {
					my $yr = ($current_yr - ${$classes{$class}}{"start_year"}) + 1;
					${$classes{$class}}{"class"} =~ s/\d+/$yr/;
					${$classes{$class}}{"year"} = $current_yr;	
				}
			}
		}
	
		#has use selected classes that can be found	
		if (keys %classes) {
			#what marksheets are there?	

			my @where_clause_bts = ();

			foreach (keys %classes) {
				push @where_clause_bts, "roll=?";
			}

			
			my $where_clause = join(" OR ", @where_clause_bts);

			my $prep_stmt_3_1 = $con->prepare("SELECT table_name,roll,exam_name,subject,time FROM marksheets WHERE $where_clause");	
			if ($prep_stmt_3_1) {
				my $rc = $prep_stmt_3_1->execute(keys %classes);
				if ($rc) {
					while (my @rslts = $prep_stmt_3_1->fetchrow_array()) {
						my ($table_name,$roll,$exam_name,$subject, $time) = @rslts;
						$marksheets{$table_name} = {"roll" => $roll, "exam_name" => $exam_name, "subject" => $subject, "time" => $time};	
						if (not exists $exam_seq{$exam_name} ) {	
							$exam_seq{$exam_name} = $time;
						}
						else {
							if ($exam_seq{$exam_name} < $time) {
								$exam_seq{$exam_name} = $time;
							}
						}
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM marksheets statement: ", $prep_stmt_3_1->errstr, $/;
				}
			}

			else {
				print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt_3_1->errstr, $/;
			}

			#Are there any marksheets associated with the classes picked
			if (keys %marksheets) {	
				#for each class, delete the marksheets that are not for the
				#year in consideration. Doesn't make much sense...In English: if the user is
				#analysing 3B(2015), delete all marksheets whose year is not 2014 (in a 1-4 school system).
				for my $class (keys %classes) {
					my $yr = ${$classes{$class}}{"year"};
					for my $marksheet (keys %marksheets) {
						if (${$marksheets{$marksheet}}{"roll"} eq $class) {	
							my $exam_year = 1900 + (localtime (${$marksheets{$marksheet}}{"time"}))[5];	
							
							unless ($exam_year <= $yr) {
								delete $marksheets{$marksheet};	
							}
						}
					}
				}

				#Is there an exam lim?
				my $cntr = 0;
				if (exists $session{"exams"}) {	
					my @exam_list = split/,/,lc($session{"exams"});
				
					my %exam_list_hash = ();
					@exam_list_hash{@exam_list} = @exam_list;
			
					for my $marksheet (keys %marksheets) {
						my $exam_name = lc(${$marksheets{$marksheet}}{"exam_name"});
						if (not exists $exam_list_hash{$exam_name}) {
							delete $marksheets{$marksheet};
						}
					}
					for my $exam (keys %exam_seq) {
						my $lc_exam = lc($exam);
						if (not exists $exam_list_hash{$lc_exam}) {
							delete $exam_seq{$exam};
						}
					}
				}	
				#is there a subject lim?
				if (exists $session{"subjects"}) {
					my @subject_list = split/,/, lc($session{"subjects"});
					my %subjects_hash = ();
					@subjects_hash{@subject_list} = @subject_list;
					for my $marksheet (keys %marksheets) {
						my $subj = lc(${$marksheets{$marksheet}}{"subject"});
						unless (exists $subjects_hash{$subj}) {
							delete $marksheets{$marksheet};
						}
					}
				}
		
				if (keys %marksheets) {
					#check other conditions
					my @where_clause = ();
					my @bind_vals = ();

					#clubs_societies
					if (exists $session{"clubs_societies"}) {
						my @clubs = split/,/, lc($session{"clubs_societies"});
						my @clubs_like = ();
						for my $club (@clubs) {	
							push @clubs_like, "clubs_societies LIKE ?";
							push @bind_vals, "%$club%";
						}
						my $clubs_lim = "(" . join(" OR ", @clubs_like) . ")";
						push @where_clause, $clubs_lim;
					}

					#responsilities
					if (exists $session{"responsibilities"}) {
						my @respons = split/,/, lc($session{"responsibilities"});
						my @respons_like = ();
						for my $respon (@respons) {
							push @respons_like, "responsibilities LIKE ?";
							push @bind_vals, "%$respon%";
						}
						my $respons_lim = "(" . join(" OR ", @respons_like) . ")";
						push @where_clause, $respons_lim;
					}

					#sports_games
					if (exists $session{"sports_games"}) {
						my @games = split/,/, lc($session{"sports_games"});
						my @games_like = ();
						for my $game (@games) {
							push @games_like, "sports_games LIKE ?";
							push @bind_vals, "%$game%";
						}
						my $games_lim = "(" . join(" OR ", @games_like) . ")";
						push @where_clause, $games_lim;
					}

					#dorms
					if (exists $session{"dorms"}) {
						my @dorms = split/,/, lc($session{"dorms"});
						my @dorms_like = ();
						for my $dorm (@dorms) {
							push @dorms_like, "house_dorm LIKE ?";
							push @bind_vals, "%$dorm%";
						}
						my $dorms_lim = "(" . join(" OR ", @dorms_like) . ")";
						push @where_clause, $dorms_lim;
					}

					#marks_at_adm
					if (exists $session{"marks_at_adm"}) {
						my $lim = $session{"marks_at_adm"};
						my $marks_at_adm_lim = "(marks_at_adm $lim)";
						push @where_clause, $marks_at_adm_lim;
					}
	
					my $where = "";
					if (@where_clause) {	
						$where = " WHERE " . join(" AND ", @where_clause);
					}
	
					my $prep_stmt_3_2;			

					for my $class (keys %classes) {	
						$prep_stmt_3_2 = $con->prepare("SELECT adm,s_name,o_names,marks_at_adm,clubs_societies,sports_games,responsibilities,house_dorm FROM `${class}`${where}");
						if ($prep_stmt_3_2) {
	
							my $rc = $prep_stmt_3_2->execute(@bind_vals);

							if ($rc) {
								while (my @rslts = $prep_stmt_3_2->fetchrow_array()) {
									#How to handle blanks
									for (my $i = 0;$i < @rslts; $i++) {
										if (not defined ($rslts[$i]) or $rslts[$i] eq "") {
											$rslts[$i] = "None";
										}
									}
									$matching_adms{$rslts[0]} = {"Name" => "$rslts[1] $rslts[2]", "Class" => ${$classes{$class}}{"class"}, "Marks at Admission" => $rslts[3], "Clubs/Societies" => $rslts[4], "Sports/Games" => $rslts[5], "Responsibilities" => $rslts[6], "Dorm" => $rslts[7]};
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM $class statement: ", $prep_stmt_3_2->errstr, $/;
							}	
						}
						else {
							print STDERR "Could not prepare SELECT FROM $class statement: ", $prep_stmt_3_2->errstr, $/;
						}
					}
					my $dataset_size = scalar(keys %matching_adms);

					if ($dataset_size > 0) {

						my %remaining_exams;
						for my $marksheet_3 (keys %marksheets) {
							$remaining_exams{${$marksheets{$marksheet_3}}{"exam_name"}}++;
						}

						for my $exam_9 (keys %exam_seq) {
							delete $exam_seq{$exam_9} unless (exists $remaining_exams{$exam_9});
						} 
						
						
#Group by
G_BY: {
if ($session{"analysis_type"} eq "group_by") {
	
	$group_by = "Class";
	my $marks_at_adm_group_step = 50;
	
	if (exists $auth_params{"group_by"}) {
		$group_by = $auth_params{"group_by"};
		unless ($group_by eq "Clubs/Societies" or $group_by eq "Responsibilities" or $group_by eq "Sports/Games" or $group_by eq "Class" or $group_by eq "Dorm" or $group_by eq "Marks at Admission") {
		$group_by = "Class";
		}
	}
							
	if (exists $auth_params{"batches"}) {
		my $possib_batches = $auth_params{"batches"};
		if ($possib_batches == 20 or $possib_batches == 50 or $possib_batches == 100) {
			$marks_at_adm_group_step = $possib_batches;
		}
	}

	my ($show_means, $show_grading, $show_top, $show_bottom, $show_improved, $show_declined, $show_graphs) =  (0,0,0,0,0,0,0);
	my ($top_limit, $bottom_limit, $improved_limit, $declined_limit) = (3,3,3,3);

	my $anal_scope = 0;
	if (exists $auth_params{"scope_averages"}) {
		$anal_scope++;
		$show_means++;
	}

	if (exists $auth_params{"scope_top"}) {
		$anal_scope++;
		$show_top++;
		$top_limit = 3;
		if (exists $auth_params{"top_limit"} and $auth_params{"top_limit"} =~ /^\d+$/) {
			$top_limit = $auth_params{"top_limit"};
		}
	}

	if (exists $auth_params{"scope_bottom"}) {
		$anal_scope++;
		$show_bottom++;
		$bottom_limit = 3;
		if (exists $auth_params{"bottom_limit"} and $auth_params{"bottom_limit"} =~ /^\d+$/) {
			$bottom_limit = $auth_params{"bottom_limit"};
		}
	}

	if (exists $auth_params{"scope_improved"}) {
		$anal_scope++;
		$show_improved++;
		$improved_limit = 3;
		if (exists $auth_params{"improved_limit"} and $auth_params{"improved_limit"} =~ /^\d+$/) {
			$improved_limit = $auth_params{"improved_limit"};
		}
	}

	if (exists $auth_params{"scope_declined"}) {
		$anal_scope++;
		$show_declined++;
		$declined_limit = 3;
		if (exists $auth_params{"declined_limit"} and $auth_params{"declined_limit"} =~ /^\d+$/) {
			$declined_limit = $auth_params{"declined_limit"};
		}
	}

	if (exists $auth_params{"scope_graphs"}) {
		$anal_scope++;
		$show_graphs++;
		$show_means++;
	}

	if (exists $auth_params{"scope_grades"}) {
		$anal_scope++;
		$show_grading++;
	}
	#No scope specified
	#Quit with warning
	unless ($anal_scope) {
		$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
</head>
<body>
$header
<p><em>Dataset size: $dataset_size</em>&nbsp;(<a href="/cgi-bin/viewdataset.cgi" target="_blank">View Dataset</a>)
<p><em><span style="color: red">No analysis scope specified</span>. To run an analysis, please specify at-least 1 analysis scope (e.g. 'Averages and Standards Deviations' or 'Top Students')</em>
</body></html>
*;

		last G_BY;
	}
	my %exam_to_delta_pair;
	#serious bug arising from mishandling 
	#of this delta_pair business.
	#I'm only now beginning to grasp the 
	#immense fcuk up I made.
	my @sorted_exam_list = sort { $exam_seq{$a} <=> $exam_seq{$b} } keys %exam_seq;
	if (scalar(@sorted_exam_list) > 1) {
		$exam_to_delta_pair{$sorted_exam_list[0]} = "^;$sorted_exam_list[0] - $sorted_exam_list[1]"; 
		for (my $i = 1; $i < scalar(@sorted_exam_list) - 1; $i++) {
			my $delta_pair_1 = $sorted_exam_list[$i - 1] . " - " . $sorted_exam_list[$i];
			my $delta_pair_2 = $sorted_exam_list[$i] . " - " . $sorted_exam_list[$i+1];
	
			$exam_to_delta_pair{$sorted_exam_list[$i]} = "$delta_pair_1;$delta_pair_2";
		}
		$exam_to_delta_pair{$sorted_exam_list[scalar(@sorted_exam_list) - 1]} =  $sorted_exam_list[scalar(@sorted_exam_list) - 2] . " - " . $sorted_exam_list[scalar(@sorted_exam_list) - 1] . ";\$";
	}

	my (  %matched_most_improved_overall,   %matched_most_improved_group);
	my (%unmatched_most_improved_overall, %unmatched_most_improved_group);

	my (  %matched_most_declined_overall,   %matched_most_declined_group);	
 
	my (%best_studs_overall, %best_studs_group);
	my (%worst_studs_overall, %worst_studs_group);

	my %stud_means;
	my %means;	

	my %subjects;	
	my %subj_cntr = ();

	my (%grade_distribution_overall, %grade_distribution_group);	
	
	#grading
	if ($show_grading) {
	my $prep_stmt6 = $con->prepare("SELECT id,value FROM vars WHERE id='1-grading' OR id='1-points' LIMIT 2");

	if ($prep_stmt6) {
		my $rc = $prep_stmt6->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt6->fetchrow_array()) {
			#if (@rslts) {

				if ($rslts[0] eq "1-grading") {

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
			elsif ($rslts[0] eq "1-points") {

				my $points_str = $rslts[1];
				my @points_bts = split/,/,$points_str;

				foreach (@points_bts) {
					if ($_ =~ /^([^:]+):\s*(.+)/) {

						my ($grade,$point_s) = ($1,$2);
						$points{$grade} = $point_s;

						#print "X-Debug-2: $grade --- $point_s\r\n";
						$points_to_grade{$point_s} = $grade;

					}
				}

			}
			}
		#}
		}
		else {
			print STDERR "Could not execute SELECT FROM vars statement: ", $prep_stmt6->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt6->errstr, $/;
	}
	#}
	}

	my $cntr = 0;
	for my $marksheet (sort marksheet_sort keys %marksheets) {
		my @data_set_list;

		#order subjects
		my $subject   = ${$marksheets{$marksheet}}{"subject"};
		my $exam_name = ${$marksheets{$marksheet}}{"exam_name"};
		my @delta_pairs = split/;/,$exam_to_delta_pair{$exam_name};

		#print "X-Debug-2-$marksheet: splits into " . join(', ', @delta_pairs) . "\r\n";	
		my $twin_exam_name;
	
		my @twins = split/\s\-\s/, $delta_pairs[0];	

		if ($twins[0] eq $exam_name) {
			$twin_exam_name = $twins[1];
		}
		else {
			$twin_exam_name = $twins[0];
		}

		#print qq%X-Debug-0-$marksheet: from ${$marksheets{$marksheet}}{"roll"}\r\n%;
		unless (exists $best_studs_overall{$exam_name}) {
			$best_studs_overall{$exam_name} = {"best_overall" => {}};
			$worst_studs_overall{$exam_name} = {"best_overall" => {}};
			#the reference illness is so deep in
			#me I'm shocked I didn't do a ref here
			#my shock wasn't unfounded-- I SHOULD have
			#done a ref
			$grade_distribution_overall{$exam_name} = {"overall" => {}};

			
			unless (exists $matched_most_improved_overall{$delta_pairs[0]}) {
				#moving unmatched in here
				#changing from {exam_name} to {delta_pair}
				${$unmatched_most_improved_overall{$delta_pairs[0]}}{"best_overall"} = {};	
				${$matched_most_improved_overall{$delta_pairs[0]}}{"best_overall"} = {};
				${$matched_most_declined_overall{$delta_pairs[0]}}{"best_overall"} = {};
				
			}

			unless (exists $matched_most_improved_overall{$delta_pairs[1]}) {
				#moving unmatched in here
				#changing from {exam_name} to {delta_pair}
				${$unmatched_most_improved_overall{$delta_pairs[1]}}{"best_overall"} = {};	
				${$matched_most_improved_overall{$delta_pairs[1]}}{"best_overall"} = {};
				${$matched_most_declined_overall{$delta_pairs[1]}}{"best_overall"} = {};
			
			}	
		}
		unless (exists ${$best_studs_overall{$exam_name}}{$subject}) {
			${$best_studs_overall{$exam_name}}{$subject} = {};
			${$worst_studs_overall{$exam_name}}{$subject} = {};

			${$grade_distribution_overall{$exam_name}}{$subject} = {};
	
			unless (exists ${$matched_most_improved_overall{$delta_pairs[0]}}{$subject}) {
				${$unmatched_most_improved_overall{$delta_pairs[0]}}{$subject} = {};
				${$matched_most_improved_overall{$delta_pairs[0]}}{$subject} = {};
				${$matched_most_declined_overall{$delta_pairs[0]}}{$subject} = {};
		
			}
			
			unless (exists ${$matched_most_improved_overall{$delta_pairs[1]}}{$subject}) {
				${$unmatched_most_improved_overall{$delta_pairs[1]}}{$subject} = {};
				${$matched_most_improved_overall{$delta_pairs[1]}}{$subject} = {};
				${$matched_most_declined_overall{$delta_pairs[1]}}{$subject} = {};	
			}
		
		}
			
		unless (exists $subjects{$exam_name}) {
			$subjects{$exam_name} = ();
			$subj_cntr{$exam_name} = 0;
		}

		unless (exists ${$subjects{$exam_name}}{$subject}) {
			${$subjects{$exam_name}}{$subject} = $subj_cntr{$exam_name}++;
		}

		my $prep_stmt_3_3 = $con->prepare("SELECT adm,marks FROM `$marksheet`");	

		if ($prep_stmt_3_3) {
			my $rc = $prep_stmt_3_3->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt_3_3->fetchrow_array()) {
					next unless (defined $rslts[0] and defined $rslts[1]);
					if (exists $matching_adms{$rslts[0]}) {
						#Knuth's single-pass mean/variance
						#mean for the student
						#what grade did this student have before?
						#get rid of that
						my $prev_grade;
						if ($show_grading) {			
							$prev_grade = get_grade(${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"});	
							${${$grade_distribution_overall{$exam_name}}{"overall"}}{$prev_grade}--;
							if (${${$grade_distribution_overall{$exam_name}}{"overall"}}{$prev_grade} <= 0) {
								delete ${${$grade_distribution_overall{$exam_name}}{"overall"}}{$prev_grade};
							}
						}

						${${$stud_means{$rslts[0]}}{$exam_name}}{"count"}++;
						if (exists ${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"}) {
							my $diff = $rslts[1] - ${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"};
							${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"} += sprintf("%.3f", $diff / ${${$stud_means{$rslts[0]}}{$exam_name}}{"count"});

						}
						else {
							${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"} = $rslts[1];
						}
						#print qq%X-Debug-2c-$rslts[0]: $exam_name(${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"})\r\n%;
						#update best|worst_studs_overall(exam, subject);
						if ($show_top) {
							do_add(${$best_studs_overall{$exam_name}}{$subject}, $rslts[0],$rslts[1], 1, $top_limit);
						}
						if ($show_bottom) {
							do_add(${$worst_studs_overall{$exam_name}}{$subject}, $rslts[0],$rslts[1], 0, $bottom_limit);
						}
						my $subj_grade;
						if ($show_grading) {
							$subj_grade = get_grade($rslts[1]);
							${${$grade_distribution_overall{$exam_name}}{$subject}}{$subj_grade}++;
						}
						if ($show_improved || $show_declined) {
						#update most improved for this subject
						#Not seen the Gemini twin for this exam/subject; save it
						#Already seen the Gemini twin; compute their diff, save this; delete the twin	
						if ( exists ${${$unmatched_most_improved_overall{$delta_pairs[0]}}{$subject}}{$rslts[0]}  ) {
							
							my $diff = $rslts[1] - ${${$unmatched_most_improved_overall{$delta_pairs[0]}}{$subject}}{$rslts[0]};

							#delete ${${$unmatched_most_improved_overall{$delta_pairs[0]}}{$subject}}{$rslts[0]};		
							#print "X-Debug-3-$marksheet-$rslts[0]: $exam_name; seen partner of $delta_pairs[0]: $diff\r\n";	
							if ($show_improved) {
							do_add(${$matched_most_improved_overall{$delta_pairs[0]}}{$subject}, $rslts[0], $diff, 1, $improved_limit);	
							}
							if ($show_declined) {
							do_add(${$matched_most_declined_overall{$delta_pairs[0]}}{$subject}, $rslts[0], $diff, 0, $declined_limit);	
							}
						}
							
						#print "X-Debug-0-$marksheet: set $delta_pairs[1]\r\n";
						${${$unmatched_most_improved_overall{$delta_pairs[1]}}{$subject}}{$rslts[0]} = $rslts[1];
						
						}
						if ($show_top) {
							#update best_studs_overall(exam best_overall)
							do_add(${$best_studs_overall{$exam_name}}{"best_overall"}, $rslts[0], ${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"}, 1, $top_limit);
						}
						if ($show_bottom) {
							do_add(${$worst_studs_overall{$exam_name}}{"best_overall"}, $rslts[0], ${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"}, 0, $bottom_limit);
						}
						my $overall_grade;
						if ($show_grading) {
							$overall_grade = get_grade(${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"});
							${${$grade_distribution_overall{$exam_name}}{"overall"}}{$overall_grade}++;
						}
						if ($show_improved or $show_declined) {
						#update most improved overall
						#Not seen the Gemini twin for this exam; save it
						if ( exists ${${$stud_means{$rslts[0]}}{$twin_exam_name}}{"mean"} ) {
							my $diff = ${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"} - ${${$stud_means{$rslts[0]}}{$twin_exam_name}}{"mean"};	
							if ($show_improved) {
							$cntr++;
							do_add(${$matched_most_improved_overall{$delta_pairs[0]}}{"best_overall"}, $rslts[0], $diff, 1, $improved_limit);
							#print qq%X-Debug-1a-$cntr: $delta_pairs[0] added $rslts[0]($diff) from ${$marksheets{$marksheet}}{"roll"}; best_overall now contains: % .join(", ", keys %{${$matched_most_improved_overall{$delta_pairs[0]}}{"best_overall"}} ) . qq%\r\n%;
							}
							if ($show_declined) {
							$cntr++;
							do_add(${$matched_most_declined_overall{$delta_pairs[0]}}{"best_overall"}, $rslts[0], $diff, 0, $declined_limit);
							#print qq%X-Debug-1b-$cntr: $delta_pairs[0] added $rslts[0]($diff) from ${$marksheets{$marksheet}}{"roll"}; best_overall now contains: % .join(", ", keys %{${$matched_most_declined_overall{$delta_pairs[0]}}{"best_overall"}} ) . qq%\r\n%;	
							}
						}
						}
						#check	
						my @pcs = ();
						if ($group_by eq "Marks at Admission") {
							if (${$matching_adms{$rslts[0]}}{"Marks at Admission"} =~ /^(\d+)$/) {
								#presumably cheaper than another de-ref
								my $marks = $1;
								#say int(63 / 50) * 50 == 1 * 50 == 50 
								my $group_start = int($1 / $marks_at_adm_group_step) * $marks_at_adm_group_step;
								#say 50 . "-" . (50 + (50 - 1)) == "50-99"
								my $group = $group_start . "-" . ($group_start + ($marks_at_adm_group_step - 1));
								@pcs = ($group);
							}
							else {
								@pcs = ("-");
							}
						}
						else {	
							@pcs = split/,/, ${$matching_adms{$rslts[0]}}{$group_by};
						}
						for my $pc (@pcs) {

							unless (exists $means{$pc}) {
								$means{$pc} = { };
								$best_studs_group{$pc} = {};
								$worst_studs_group{$pc} = {};

								$grade_distribution_group{$pc} = {};

								$unmatched_most_improved_group{$pc} = {};
								$matched_most_improved_group{$pc} = {};	
								$matched_most_declined_group{$pc} = {};
							}

							unless (exists ${$means{$pc}}{$exam_name}) {
								${$means{$pc}}{$exam_name} = {"count" => 0, "mean" => 0, "sum_squares" => 0 };
								 ${$best_studs_group{$pc}}{$exam_name} = { "best_overall" => {} };
								${$worst_studs_group{$pc}}{$exam_name} = { "best_overall" => {} };

								${$grade_distribution_group{$pc}}{$exam_name} = {"overall" => {}};
	
								if ($show_improved or $show_declined) {
								unless (exists ${$matched_most_improved_group{$pc}}{$delta_pairs[0]} ) {	
									${$unmatched_most_improved_group{$pc}}{$delta_pairs[0]} = {"best_overall" => {}};
									${$matched_most_improved_group{$pc}}{$delta_pairs[0]} = {"best_overall" => {}};
									${$matched_most_declined_group{$pc}}{$delta_pairs[0]} = {"best_overall" => {}};
								}

								unless ( exists ${$matched_most_improved_group{$pc}}{$delta_pairs[1]} ) {	
									${$unmatched_most_improved_group{$pc}}{$delta_pairs[1]} = {"best_overall" => {}};
									${$matched_most_improved_group{$pc}}{$delta_pairs[1]} = {"best_overall" => {}};
									${$matched_most_declined_group{$pc}}{$delta_pairs[1]} = {"best_overall" => {}};
								}
								}
							}

							unless (exists ${${$means{$pc}}{$exam_name}}{$subject}) {
								${${$means{$pc}}{$exam_name}}{$subject} = {"mean" => 0, "count" => 0, "sum_squares" => 0};
								 ${${$best_studs_group{$pc}}{$exam_name}}{$subject} = {};
								${${$worst_studs_group{$pc}}{$exam_name}}{$subject} = {};

								if ($show_grading) {
									${${$grade_distribution_group{$pc}}{$exam_name}}{$subject} = {};
								}

								if ($show_improved or $show_declined) {	
								unless (exists ${${$matched_most_improved_group{$pc}}{$delta_pairs[0]}}{$subject}) {
									${${$unmatched_most_improved_group{$pc}}{$delta_pairs[0]}}{$subject} = {};
									${${$matched_most_improved_group{$pc}}{$delta_pairs[0]}}{$subject} = {};
									${${$matched_most_declined_group{$pc}}{$delta_pairs[0]}}{$subject} = {};
								}
								unless (exists ${${$matched_most_improved_group{$pc}}{$delta_pairs[1]}}{$subject}) {
									${${$unmatched_most_improved_group{$pc}}{$delta_pairs[1]}}{$subject} = {};
									${${$matched_most_improved_group{$pc}}{$delta_pairs[1]}}{$subject} = {};
									${${$matched_most_declined_group{$pc}}{$delta_pairs[1]}}{$subject} = {};
								}
								}
							}
							if ($show_top) {
							#update best|worst in group (exam, best_overall)
							do_add(${${$best_studs_group{$pc}}{$exam_name}}{"best_overall"}, $rslts[0], ${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"}, 1, $top_limit);
							}
							if ($show_bottom) {
							do_add(${${$worst_studs_group{$pc}}{$exam_name}}{"best_overall"}, $rslts[0], ${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"}, 0, $bottom_limit);
							}

							if ($show_grading) {	
								${${${$grade_distribution_group{$pc}}{$exam_name}}{"overall"}}{$prev_grade}--;
								if (${${${$grade_distribution_group{$pc}}{$exam_name}}{"overall"}}{$prev_grade} <= 0) {
									delete ${${${$grade_distribution_group{$pc}}{$exam_name}}{"overall"}}{$prev_grade};
								}
							
								${${${$grade_distribution_group{$pc}}{$exam_name}}{"overall"}}{$overall_grade}++;
							}

							if ($show_top) {
							#update best|worst in group(exam, subject)
							do_add(${${$best_studs_group{$pc}}{$exam_name}}{$subject}, $rslts[0], $rslts[1], 1, $top_limit);
							}
							if ($show_bottom) {
							do_add(${${$worst_studs_group{$pc}}{$exam_name}}{$subject}, $rslts[0], $rslts[1], 0, $bottom_limit);
							}

							if ($show_grading) {
								#add subj
								${${${$grade_distribution_group{$pc}}{$exam_name}}{$subject}}{$subj_grade}++;
							}

							if ($show_improved or $show_declined) {
							#update most improved for this subject
							#Not seen the Gemini twin for this exam/subject; save it
							#Already seen the Gemini twin; compute their diff, save this; delete the twin
							if (exists ${${${$unmatched_most_improved_group{$pc}}{$delta_pairs[0]}}{$subject}}{$rslts[0]} ) {	
								my $diff = $rslts[1] - ${${${$unmatched_most_improved_group{$pc}}{$delta_pairs[0]}}{$subject}}{$rslts[0]};	
								if ($show_improved) {
								do_add(${${$matched_most_improved_group{$pc}}{$delta_pairs[0]}}{$subject}, $rslts[0], $diff, 1, $improved_limit);	
								}
								if ($show_declined) {
								do_add(${${$matched_most_declined_group{$pc}}{$delta_pairs[0]}}{$subject}, $rslts[0], $diff, 0, $declined_limit);	
								}
							}
							
							${${${$unmatched_most_improved_group{$pc}}{$delta_pairs[1]}}{$subject}}{$rslts[0]} = $rslts[1];	
							}
							if ($show_improved or $show_declined) {
							#update most improved overall
							#Not seen the Gemini twin for this exam; save it

							#Already seen the Gemini twin; compute their diff, save this; delete the twin
							if ( exists ${${$stud_means{$rslts[0]}}{$twin_exam_name}}{"mean"} ) {
								my $diff = ${${$stud_means{$rslts[0]}}{$exam_name}}{"mean"} - ${${$stud_means{$rslts[0]}}{$twin_exam_name}}{"mean"};

								if ($show_improved) {
								do_add(${${$matched_most_improved_group{$pc}}{$delta_pairs[0]}}{"best_overall"}, $rslts[0], $diff, 1, $improved_limit);
								}
								if ($show_declined) {
								do_add(${${$matched_most_declined_group{$pc}}{$delta_pairs[0]}}{"best_overall"}, $rslts[0], $diff, 0, $declined_limit);
								}
							}
							#${${${$unmatched_most_improved_group{$pc}}{$delta_pairs[1]}}{"best_overall"}}{$rslts[0]} = $rslts[1];	
							}

							if ($show_means) {
								if (exists ${${${$means{$pc}}{$exam_name}}{$subject}}{"mean"}) {
									#Knuth's single-pass mean/variance
									${${${$means{$pc}}{$exam_name}}{$subject}}{"count"}++;
									my $diff = $rslts[1] - ${${${$means{$pc}}{$exam_name}}{$subject}}{"mean"};
									${${${$means{$pc}}{$exam_name}}{$subject}}{"mean"} += ($diff / ${${${$means{$pc}}{$exam_name}}{$subject}}{"count"});
									${${${$means{$pc}}{$exam_name}}{$subject}}{"sum_squares"} += ($diff * ($rslts[1] - ${${${$means{$pc}}{$exam_name}}{$subject}}{"mean"}));
								}
								else {
									${${${$means{$pc}}{$exam_name}}{$subject}}{"mean"} = $rslts[1];
								}
							}
						}
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM $marksheet statement: ", $prep_stmt_3_3->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM $marksheet statement: ", $prep_stmt_3_3->errstr, $/;
		}
	}	

	my %best_subject_score;
	my %subj_means;
	if ($show_means) {
	
	#work out subject means, mean scores, best score per subject, overall means	
	for my $pc (keys %means) {
		for my $exam (keys %{$means{$pc}}) {
			unless (exists $subj_means{$exam}) {
				$subj_means{$exam} = {"mean" => 0, "count" => 0};
			}
			for my $subj (keys %{${$means{$pc}}{$exam}}) {
				#Avoid processing count, mean, sum_squares etc
				next unless (exists ${$subjects{$exam}}{$subj});	
			
				my $cnt = ${${${$means{$pc}}{$exam}}{$subj}}{"count"};
				$cnt-- if ($cnt > 1);
	
				${${${$means{$pc}}{$exam}}{$subj}}{"sum_squares"} = ${${${$means{$pc}}{$exam}}{$subj}}{"sum_squares"} / $cnt;
				${${${$means{$pc}}{$exam}}{$subj}}{"std_dev"} = sqrt( ${${${$means{$pc}}{$exam}}{$subj}}{"sum_squares"} );
		
				#best subject scores/exam
				unless (exists ${$best_subject_score{$exam}}{$subj}) {
					${$best_subject_score{$exam}}{$subj} = sprintf("%.3f", ${${${$means{$pc}}{$exam}}{$subj}}{"mean"});
					${$subj_means{$exam}}{$subj} = {"mean" => 0, "count" => 0};	
				}

				if (${${${$means{$pc}}{$exam}}{$subj}}{"mean"} > ${$best_subject_score{$exam}}{$subj}) {
					${$best_subject_score{$exam}}{$subj} = sprintf("%.3f", ${${${$means{$pc}}{$exam}}{$subj}}{"mean"});	
				}
				
				#Mean score for $pc
				${${$means{$pc}}{$exam}}{"count"}++;
				my $diff = ${${${$means{$pc}}{$exam}}{$subj}}{"mean"} - ${${$means{$pc}}{$exam}}{"mean"};
				${${$means{$pc}}{$exam}}{"mean"} += $diff / ${${$means{$pc}}{$exam}}{"count"};	

				#Mean for the subject
				${${$subj_means{$exam}}{$subj}}{"count"}++;
				#The mean is a mean of means so don't mind
				#the double mean in the statements
				$diff = ${${${$means{$pc}}{$exam}}{$subj}}{"mean"} - ${${$subj_means{$exam}}{$subj}}{"mean"};
				${${$subj_means{$exam}}{$subj}}{"mean"} += ($diff / ${${$subj_means{$exam}}{$subj}}{"count"});
		
				#round off mean,stddev to 3 dp
				${${${$means{$pc}}{$exam}}{$subj}}{"std_dev"} = sprintf ("%.3f",  ${${${$means{$pc}}{$exam}}{$subj}}{"std_dev"});
				${${${$means{$pc}}{$exam}}{$subj}}{"mean"} = sprintf ("%.3f",  ${${${$means{$pc}}{$exam}}{$subj}}{"mean"});
			}

		}
	}

	#Mean & sum of squares for the exam(s)
	for my $pc_2 (keys %means) {
		for my $exam (keys %{$means{$pc_2}}) {
			#std_dev for exam
			${$subj_means{$exam}}{"count"}++;
			my $diff = ${${$means{$pc_2}}{$exam}}{"mean"} - ${$subj_means{$exam}}{"mean"};
			${$subj_means{$exam}}{"mean"} += ($diff / ${$subj_means{$exam}}{"count"});	
			${${$means{$pc_2}}{$exam}}{"mean"} = sprintf("%.3f", ${${$means{$pc_2}}{$exam}}{"mean"});
		}
	}
	#std_devs for whole exams & subjects
	for my $exam_5 (keys %exam_seq) {
		for my $subj (keys %{$subj_means{$exam_5}}) {	
			#overall means/std_devs
			#avoid doing ish on count, mean, sum_squares etc
			next unless (exists ${$subjects{$exam_5}}{$subj});
			
			#round off to 3 dp
			${${$subj_means{$exam_5}}{$subj}}{"mean"} = sprintf("%.3f", ${${$subj_means{$exam_5}}{$subj}}{"mean"});	
		}

		${$subj_means{$exam_5}}{"mean"} = sprintf("%.3f", ${$subj_means{$exam_5}}{"mean"});
	}
	}

	my %headed;
	my $data_str = "";

	if ($show_means) {
	#got the idea to use rules between exams &
	#analysis categories
	$data_str = qq!<hr style="height: 4px; color: black; background-color: black"><h2>Averages and Standard Deviations</h2><p><em>NB: The numbers in brackets are the standard devitions for the averages e.g. 60.570(3.200) means an average of 60.57 with a standard deviation of 3.2.</em>!;
	

	for my $exam_4 (sort {$exam_seq{$a} <=> $exam_seq{$b}} keys %exam_seq) {	

		$data_str .= 
qq!
<hr style="height: 2px; color: black; background-color: black"><p><h3>$exam_4</h3>
<table border="1">
<thead><th>$group_by
!;
		for my $pc (sort { ${${$means{$b}}{$exam_4}}{"mean"} <=> ${${$means{$a}}{$exam_4}}{"mean"} } keys %means) {		
			for my $exam_2 (keys %{$means{$pc}}) {
				#Effectively reverses the $pc->$exam order	

				next unless ($exam_2 eq $exam_4);	
				unless (exists $headed{$exam_4}) {				
					for my $subj_lst ( sort { ${$subjects{$exam_4}}{$a} <=> ${$subjects{$exam_4}}{$b} }  keys %{$subjects{$exam_4}} ) {
						$data_str .= "<th>$subj_lst";
					}
					$data_str .= "<th>Mean Score</thead><tbody>";
					$headed{$exam_4}++;
				}

				$data_str .= "<tr><td>$pc"; 
				my @data = ();
				for (my $i = 0; $i < scalar(keys %{$subjects{$exam_4}}); $i++) {
					$data[$i] = "<td>&nbsp;</td>";
				}
				
				for my $subj ( sort { ${$subjects{$exam_4}}{$a} <=> ${$subjects{$exam_4}}{$b} } keys %{$subjects{$exam_4}}) {
					next unless exists (${${${$means{$pc}}{$exam_4}}{$subj}}{"mean"});
					my $score = ${${${$means{$pc}}{$exam_4}}{$subj}}{"mean"};
					my $std_dev = ${${${$means{$pc}}{$exam_4}}{$subj}}{"std_dev"};
					if ($score == ${$best_subject_score{$exam_4}}{$subj}) {
						$data[${$subjects{$exam_4}}{$subj}] = qq!<td style="font-weight: bold">$score($std_dev)!;
					}
					else {
						$data[${$subjects{$exam_4}}{$subj}] = "<td>" . $score . "($std_dev)";
					}
				}

				$data_str .= join("", @data);	
				$data_str .= qq!<td style="font-weight: bold">${${$means{$pc}}{$exam_4}}{"mean"}!;
			}
		}
		#Add overall means per subject	
		$data_str .= qq!<tr style="font-weight: bold"><td>All!;
		my @data = ();
		for (my $i = 0; $i < scalar(keys %{$subjects{$exam_4}}); $i++) {
			$data[$i] = "<td>&nbsp;</td>";
		}
	
		for my $subj ( sort { ${$subjects{$exam_4}}{$a} <=> ${$subjects{$exam_4}}{$b} }  keys %{$subjects{$exam_4}}) {	
			$data[${$subjects{$exam_4}}{$subj}] = qq!<td>${${$subj_means{$exam_4}}{$subj}}{"mean"}!;
		}
	 		
		$data_str .= join("", @data);
		$data_str .= qq!<td>${$subj_means{$exam_4}}{"mean"}</tbody></table><hr style="height: 2px; color: black; background-color: black">!;
	}

	}

	if ($show_grading) {
	%headed = ();
	#Best students
	$data_str .= qq!<hr style="height: 4px; color: black; background-color: black"><p><h2>Grade Distribution per $group_by</h2>!;	
	for my $exam_5 (sort {$exam_seq{$a} <=> $exam_seq{$b}} keys %exam_seq) {

		$data_str .= 
qq!
<hr style="height: 2px; color: black; background-color: black"><p><h3>$exam_5</h3>
<table border="1">
<thead><th>$group_by
!;
		for my $pc (sort { ${${$means{$b}}{$exam_5}}{"mean"} <=> ${${$means{$a}}{$exam_5}}{"mean"} } keys %means) {		

			for my $exam_2 (keys %{$means{$pc}}) {

				#Effectively reverses the $pc->$exam order	

				next unless ($exam_2 eq $exam_5);	
				unless (exists $headed{$exam_5}) {				
					for my $subj_lst ( sort { ${$subjects{$exam_5}}{$a} <=> ${$subjects{$exam_5}}{$b} }  keys %{$subjects{$exam_5}} ) {
						$data_str .= "<th>$subj_lst";
					}
					$data_str .= "<th>Mean score</thead><tbody>";
					$headed{$exam_5}++;
				}

				$data_str .= "<tr><td>$pc"; 
				my @data = ();
				for (my $i = 0; $i < scalar(keys %{$subjects{$exam_5}}); $i++) {
					$data[$i] = "<td>&nbsp;</td>";
				}
				
				for my $subj ( sort { ${$subjects{$exam_5}}{$a} <=> ${$subjects{$exam_5}}{$b} } keys %{$subjects{$exam_5}}) {

					my ($mean_grade,$median_grade,$total_pts, $stud_cnt) = ("","",0,0);
					my @all_grades = ();

					for my $grade ( keys %{${${$grade_distribution_group{$pc}}{$exam_5}}{$subj}} ) {

						my $num_studs = ${${$grade_distribution_group{$pc}}{$exam_5}}{$subj}->{$grade};

						my $grade_pts = $points{$grade};
						#print "X-Debug: $grade -- $num_studs -- $grade_pts\r\n";

						$total_pts += ($grade_pts * $num_studs);
						$stud_cnt += $num_studs;

						foreach (1..$num_studs) {
							push @all_grades, $grade; 
						}

					}

					if ($total_pts > 0) {
						
						my $mean_pts = sprintf("%.0f", ($total_pts / $stud_cnt));
						$mean_grade = $points_to_grade{$mean_pts};

					}
					if (scalar(@all_grades) > 0) {
						$median_grade = $all_grades[int(scalar(@all_grades) / 2)];
					}

					my $list = return_ordered_grades(${${$grade_distribution_group{$pc}}{$exam_5}}{$subj});
					$data[${$subjects{$exam_5}}{$subj}] = "<td>" . $list . qq!<BR><SPAN style="font-weight: bold">Mean grade:&nbsp;$mean_grade<BR>Median grade:&nbsp;$median_grade</SPAN>!;
				}

				my ($mean_grade,$median_grade,$total_pts, $stud_cnt) = ("","",0,0);
				my @all_grades = ();

				for my $grade ( keys %{${${$grade_distribution_group{$pc}}{$exam_5}}{"overall"}} ) {

					my $num_studs = ${${$grade_distribution_group{$pc}}{$exam_5}}{"overall"}->{$grade};

					my $grade_pts = $points{$grade};
					#print "X-Debug: $grade -- $num_studs -- $grade_pts\r\n";

					$total_pts += ($grade_pts * $num_studs);
					$stud_cnt += $num_studs;

					foreach (1..$num_studs) {
						push @all_grades, $grade; 
					}
				}

				if ($total_pts > 0) {
					my $mean_pts = sprintf("%.0f", ($total_pts / $stud_cnt));
					$mean_grade = $points_to_grade{$mean_pts};
				}

				if (scalar(@all_grades) > 0) {
					$median_grade = $all_grades[int(scalar(@all_grades) / 2)];
				}
				$data_str .= join("", @data);

				my $overall_group = return_ordered_grades(${${$grade_distribution_group{$pc}}{$exam_5}}{"overall"});	
				$data_str .= qq!<td style="font-weight: bold">$overall_group! . "<BR>Mean grade:&nbsp;$mean_grade<BR>Median grade:&nbsp;$median_grade";
			}
		}

		#Add overall best per subject & overall best by mean	
		$data_str .= qq!<tr style="font-weight: bold"><td>All!;
		my @data = ();
		for (my $i = 0; $i < scalar(keys %{$subjects{$exam_5}}); $i++) {
			$data[$i] = "<td>&nbsp;</td>";
		}
	
		for my $subj ( sort { ${$subjects{$exam_5}}{$a} <=> ${$subjects{$exam_5}}{$b} }  keys %{$subjects{$exam_5}}) {

			my ($mean_grade,$median_grade,$total_pts, $stud_cnt) = ("","",0,0);
			my @all_grades = ();

			for my $grade ( keys %{${$grade_distribution_overall{$exam_5}}{$subj}} ) {

				my $num_studs = $grade_distribution_overall{$exam_5}->{$subj}->{$grade};

				my $grade_pts = $points{$grade};
				#print "X-Debug: $grade -- $num_studs -- $grade_pts\r\n";

				$total_pts += ($grade_pts * $num_studs);
				$stud_cnt += $num_studs;

				foreach (1..$num_studs) {
					push @all_grades, $grade; 
				}

			}

			if ($total_pts > 0) {
				my $mean_pts = sprintf("%.0f", ($total_pts / $stud_cnt));
				$mean_grade = $points_to_grade{$mean_pts};
			}
			if (scalar(@all_grades) > 0) {
				$median_grade = $all_grades[int(scalar(@all_grades) / 2)];
			}

			#add overall anal
			my $list = return_ordered_grades(${$grade_distribution_overall{$exam_5}}{$subj});
			$data[${$subjects{$exam_5}}{$subj}] = qq!<td>$list! . "Mean grade:&nbsp;$mean_grade<BR>Median grade&nbsp;$median_grade";

		}
	 		
		$data_str .= join("", @data);

		my ($mean_grade,$median_grade,$total_pts, $stud_cnt) = ("","",0,0);
		my @all_grades = ();

		for my $grade ( keys %{${$grade_distribution_overall{$exam_5}}{"overall"}} ) {

			my $num_studs = ${$grade_distribution_overall{$exam_5}}{"overall"}->{$grade};

			my $grade_pts = $points{$grade};
			#print "X-Debug: $grade -- $num_studs -- $grade_pts\r\n";

			$total_pts += ($grade_pts * $num_studs);
			$stud_cnt += $num_studs;

			foreach (1..$num_studs) {
				push @all_grades, $grade; 
			}
		}

		if ($total_pts > 0) {
			my $mean_pts = sprintf("%.0f", ($total_pts / $stud_cnt));
			$mean_grade = $points_to_grade{$mean_pts};
		}
		if (scalar(@all_grades) > 0) {
			$median_grade = $all_grades[int(scalar(@all_grades) / 2)];
		}

		my $overall_exam = return_ordered_grades(${$grade_distribution_overall{$exam_5}}{"overall"});
		$data_str .= qq!<td>$overall_exam<BR>Mean grade:&nbsp;$mean_grade<BR>Median grade:&nbsp;$median_grade</tbody></table><hr style="height: 2px; color: black; background-color: black">!;
	}
	}
	if ($show_top) {
	%headed = ();
	#Best students
	$data_str .= qq!<hr style="height: 4px; color: black; background-color: black"><p><h2>Top $top_limit Students per $group_by</h2>!;	
	for my $exam_5 (sort {$exam_seq{$a} <=> $exam_seq{$b}} keys %exam_seq) {	

		$data_str .= 
qq!
<hr style="height: 2px; color: black; background-color: black"><p><h3>$exam_5</h3>
<table border="1">
<thead><th>$group_by
!;
		for my $pc (sort { ${${$means{$b}}{$exam_5}}{"mean"} <=> ${${$means{$a}}{$exam_5}}{"mean"} } keys %means) {		
			for my $exam_2 (keys %{$means{$pc}}) {
				#Effectively reverses the $pc->$exam order	

				next unless ($exam_2 eq $exam_5);	
				unless (exists $headed{$exam_5}) {				
					for my $subj_lst ( sort { ${$subjects{$exam_5}}{$a} <=> ${$subjects{$exam_5}}{$b} }  keys %{$subjects{$exam_5}} ) {
						$data_str .= "<th>$subj_lst";
					}
					$data_str .= "<th>Mean score</thead><tbody>";
					$headed{$exam_5}++;
				}

				$data_str .= "<tr><td>$pc"; 
				my @data = ();
				for (my $i = 0; $i < scalar(keys %{$subjects{$exam_5}}); $i++) {
					$data[$i] = "<td>&nbsp;</td>";
				}
				
				for my $subj ( sort { ${$subjects{$exam_5}}{$a} <=> ${$subjects{$exam_5}}{$b} } keys %{$subjects{$exam_5}}) {
					my $list = return_ordered(${${$best_studs_group{$pc}}{$exam_5}}{$subj}, 1);	
					$data[${$subjects{$exam_5}}{$subj}] = "<td>" . $list;
				}

				$data_str .= join("", @data);
				my $overall_group = return_ordered(${${$best_studs_group{$pc}}{$exam_5}}{"best_overall"}, 1);	
				$data_str .= qq!<td style="font-weight: bold">$overall_group!;
			}
		}
		#Add overall best per subject & overall best by mean	
		$data_str .= qq!<tr style="font-weight: bold"><td>All!;
		my @data = ();
		for (my $i = 0; $i < scalar(keys %{$subjects{$exam_5}}); $i++) {
			$data[$i] = "<td>&nbsp;</td>";
		}
	
		for my $subj ( sort { ${$subjects{$exam_5}}{$a} <=> ${$subjects{$exam_5}}{$b} }  keys %{$subjects{$exam_5}}) {	
			my $list = return_ordered(${$best_studs_overall{$exam_5}}{$subj}, 1);
			$data[${$subjects{$exam_5}}{$subj}] = qq!<td>$list!;
		}
	 		
		$data_str .= join("", @data);
		my $overall_exam = return_ordered(${$best_studs_overall{$exam_5}}{"best_overall"}, 1);
		$data_str .= qq!<td>$overall_exam</tbody></table><hr style="height: 2px; color: black; background-color: black">!;
	}
	}

	if ($show_bottom) {	
	#Worst students
	#'worst' will be replaced with 'Bottom'
	%headed = ();
	$data_str .= qq!<hr style="height: 4px; color: black; background-color: black"><p><h2>Bottom $bottom_limit Students per $group_by</h2>!;
	my $d_cntr = 0;
	for my $exam_6 (sort {$exam_seq{$a} <=> $exam_seq{$b}} keys %exam_seq) {	

		$data_str .= 
qq!
<hr style="height: 2px; color: black; background-color: black"><p><h3>$exam_6</h3>
<table border="1">
<thead><th>$group_by
!;
		for my $pc (sort { ${${$means{$b}}{$exam_6}}{"mean"} <=> ${${$means{$a}}{$exam_6}}{"mean"} } keys %means) {		
			for my $exam_2 (keys %{$means{$pc}}) {
				#Effectively reverses the $pc->$exam order	

				next unless ($exam_2 eq $exam_6);	
				unless (exists $headed{$exam_6}) {				
					for my $subj_lst ( sort { ${$subjects{$exam_6}}{$a} <=> ${$subjects{$exam_6}}{$b} }  keys %{$subjects{$exam_6}} ) {
						$data_str .= "<th>$subj_lst";
					}
					$data_str .= "<th>Mean score</thead><tbody>";
					$headed{$exam_6}++;
				}

				$data_str .= "<tr><td>$pc"; 
				my @data = ();
				for (my $i = 0; $i < scalar(keys %{$subjects{$exam_6}}); $i++) {
					$data[$i] = "<td>&nbsp;</td>";
				}
				
				for my $subj ( sort { ${$subjects{$exam_6}}{$a} <=> ${$subjects{$exam_6}}{$b} } keys %{$subjects{$exam_6}}) {
					my $list = return_ordered(${${$worst_studs_group{$pc}}{$exam_6}}{$subj}, 1);	
					$data[${$subjects{$exam_6}}{$subj}] = "<td>" . $list;
				}

				$data_str .= join("", @data);
				my $overall_group = return_ordered(${${$worst_studs_group{$pc}}{$exam_6}}{"best_overall"}, 1);
				$data_str .= qq!<td style="font-weight: bold">$overall_group!;
			}
		}
		#Add overall best per subject & overall best by mean	
		$data_str .= qq!<tr style="font-weight: bold"><td>All!;
		my @data = ();
		for (my $i = 0; $i < scalar(keys %{$subjects{$exam_6}}); $i++) {
			$data[$i] = "<td>&nbsp;</td>";
		}
	
		for my $subj ( sort { ${$subjects{$exam_6}}{$a} <=> ${$subjects{$exam_6}}{$b} }  keys %{$subjects{$exam_6}}) {	
			my $list = return_ordered(${$worst_studs_overall{$exam_6}}{$subj}, 1);
			$data[${$subjects{$exam_6}}{$subj}] = qq!<td>$list!;
		}
	 		
		$data_str .= join("", @data);
		my $overall_exam = return_ordered(${$worst_studs_overall{$exam_6}}{"best_overall"}, 1);
		$data_str .= qq!<td>$overall_exam</tbody></table><hr style="height: 2px; color: black; background-color: black">!;
	}

	}

my %seen_pairs;
if ($show_improved or $show_declined) {
#There will be no improvements to
#gauge if only 1 exam is being analyzed

if (scalar(keys %exam_seq) > 1) {
	if ($show_improved) {
	
	%headed = ();
	$data_str .= qq!<hr style="height: 4px; color: black; background-color: black"><p><h2>$improved_limit Most Improved Students per $group_by</h2>!;

	#Most improved students
	for my $exam_7 (sort {$exam_seq{$a} <=> $exam_seq{$b}} keys %exam_seq) {	
		my $pair = (split/;/,$exam_to_delta_pair{$exam_7})[0];
		next if ($pair eq "^");	
		if (exists $seen_pairs{$pair}) {	
			next;
		}
		
		$seen_pairs{$pair}++;
		$data_str .= 
qq!
<hr style="height: 2px; color: black; background-color: black"><p><h3>$pair</h3>
<table border="1">
<thead><th>$group_by
!;
		for my $pc (sort { ${${$means{$b}}{$exam_7}}{"mean"} <=> ${${$means{$a}}{$exam_7}}{"mean"} } keys %means) {		
			for my $exam_2 (keys %{$means{$pc}}) {
				#Effectively reverses the $pc->$exam order	
	
				next unless ($exam_2 eq $exam_7);
				unless (exists $headed{$exam_7}) {				
					for my $subj_lst ( sort { ${$subjects{$exam_7}}{$a} <=> ${$subjects{$exam_7}}{$b} }  keys %{$subjects{$exam_7}} ) {
						$data_str .= "<th>$subj_lst";
					}
					$data_str .= "<th>Mean score</thead><tbody>";
					$headed{$exam_7}++;
				}

				$data_str .= "<tr><td>$pc"; 
				my @data = ();
				for (my $i = 0; $i < scalar(keys %{$subjects{$exam_7}}); $i++) {
					$data[$i] = "<td>&nbsp;</td>";
				}
				
				for my $subj ( sort { ${$subjects{$exam_7}}{$a} <=> ${$subjects{$exam_7}}{$b} } keys %{$subjects{$exam_7}}) {
					my $list = return_ordered(${${$matched_most_improved_group{$pc}}{$pair}}{$subj}, 1);
					$data[${$subjects{$exam_7}}{$subj}] = "<td>" . $list;
				}

				$data_str .= join("", @data);
				my $overall_group = return_ordered(${${$matched_most_improved_group{$pc}}{$pair}}{"best_overall"}, 1);
				$data_str .= qq!<td style="font-weight: bold">$overall_group!;
			}
		}
		#Add overall most improved & per subject
		$data_str .= qq!<tr style="font-weight: bold"><td>All!;
		my @data = ();
		for (my $i = 0; $i < scalar(keys %{$subjects{$exam_7}}); $i++) {
			$data[$i] = "<td>&nbsp;</td>";
		}
	
		for my $subj ( sort { ${$subjects{$exam_7}}{$a} <=> ${$subjects{$exam_7}}{$b} }  keys %{$subjects{$exam_7}}) {	
			my $list = return_ordered(${$matched_most_improved_overall{$pair}}{$subj}, 1);
			$data[${$subjects{$exam_7}}{$subj}] = qq!<td>$list!;
		}
	 		
		$data_str .= join("", @data);
		my $overall_exam = return_ordered(${$matched_most_improved_overall{$pair}}{"best_overall"}, 1);
		$data_str .= qq!<td>$overall_exam</tbody></table><hr style="height: 2px; color: black; background-color: black">!;
	}
	}
	if ($show_declined) { 
	#Most declined
	%headed = ();
	%seen_pairs = ();

	$data_str .= qq!<hr style="height: 4px; color: black; background-color: black"><p><h2>$declined_limit Most Declined Students per $group_by</h2>!;
	for my $exam_8 (sort {$exam_seq{$a} <=> $exam_seq{$b}} keys %exam_seq) {	
		my $pair = (split/;/,$exam_to_delta_pair{$exam_8})[0];
		next if ($pair eq "^");	
		if (exists $seen_pairs{$pair}) {
			next;
		}
		$seen_pairs{$pair}++;
		$data_str .= 
qq!
<hr style="height: 2px; color: black; background-color: black"><p><h3>$pair</h3>
<table border="1">
<thead><th>$group_by
!;
		for my $pc (sort { ${${$means{$b}}{$exam_8}}{"mean"} <=> ${${$means{$a}}{$exam_8}}{"mean"} } keys %means) {		
			for my $exam_2 (keys %{$means{$pc}}) {
				#Effectively reverses the $pc->$exam order	

				next unless ($exam_2 eq $exam_8);
				unless (exists $headed{$exam_8}) {				
					for my $subj_lst ( sort { ${$subjects{$exam_8}}{$a} <=> ${$subjects{$exam_8}}{$b} }  keys %{$subjects{$exam_8}} ) {
						$data_str .= "<th>$subj_lst";
					}
					$data_str .= "<th>Mean score</thead><tbody>";
					$headed{$exam_8}++;
				}

				$data_str .= "<tr><td>$pc"; 
				my @data = ();
				for (my $i = 0; $i < scalar(keys %{$subjects{$exam_8}}); $i++) {
					$data[$i] = "<td>&nbsp;</td>";
				}
				
				for my $subj ( sort { ${$subjects{$exam_8}}{$a} <=> ${$subjects{$exam_8}}{$b} } keys %{$subjects{$exam_8}}) {
					my $list = return_ordered(${${$matched_most_declined_group{$pc}}{$pair}}{$subj}, 1);
					$data[${$subjects{$exam_8}}{$subj}] = "<td>" . $list;
				}

				$data_str .= join("", @data);
				my $overall_group = return_ordered(${${$matched_most_declined_group{$pc}}{$pair}}{"best_overall"}, 1);
				$data_str .= qq!<td style="font-weight: bold">$overall_group!;
			}
		}
		#Add overall most improved & per subject
		$data_str .= qq!<tr style="font-weight: bold"><td>All!;
		my @data = ();
		for (my $i = 0; $i < scalar(keys %{$subjects{$exam_8}}); $i++) {
			$data[$i] = "<td>&nbsp;</td>";
		}
	
		for my $subj ( sort { ${$subjects{$exam_8}}{$a} <=> ${$subjects{$exam_8}}{$b} }  keys %{$subjects{$exam_8}}) {	
			my $list = return_ordered(${$matched_most_declined_overall{$pair}}{$subj}, 1);
			$data[${$subjects{$exam_8}}{$subj}] = qq!<td>$list!;
		}
	 		
		$data_str .= join("", @data);
		my $overall_exam = return_ordered(${$matched_most_declined_overall{$pair}}{"best_overall"}, 1);
		$data_str .= qq!<td>$overall_exam</tbody></table><hr style="height: 2px; color: black; background-color: black">!;
	}
	}
}
#Warn user that they need to select
#more that 1 exam to see most improved/decined students 
else {
$data_str .= qq!<hr style="height: 4px; color: black; background-color: black"><p><h2>$improved_limit Most Improved Students per $group_by</h2><span style="color: red">No progress data to display.</span> To see the most improved/declined students, you must select more than 1 exam to analyze!;
}
}
#don't graph if just looking at 1 exam
if ($show_graphs) {
if (scalar(keys %exam_seq) > 1) {
#Generate graphs
my $graph = qq!<hr style="height: 4px; color: black; background-color: black"><p><h2>Graphs</h2>!;
my $file_name_prefix = "analysis";

if (exists $session{"analysis_id"}) {
	$file_name_prefix = $session{"analysis_id"};
}

my @color_palette = ("#000000","#0000FF","#A52A2A","#7FFF00","#FFD700","#00FF00","#FF00FF","#6B8E23","#FFA500","#A020F0","#FF0000","#A0522D","#00FFFF","#FF7F50","#B03060","#7FFFD4","#D2691E","#B22222","#000080","#DA70D6","#FA8072","#FF6347","#40E0D0","#EE82EE","#FFFF00","#CD853F");


my $pc_cntr = 0;
my ($gnuplot_code, $gnuplot_data) = ("","");
my %missings;
my %subjects_per_pc;

#sorted to ensure same order is returned
#why is same order required? because the filenames
#of graphs will have a static index across diff plots
for my $pc_3 ( sort {$a cmp $b} keys %means ) {
	#my $r_code = "";

	$gnuplot_code .= 
qq%set terminal png size 700,700;\\
set output '${doc_root}/images/graphs/$file_name_prefix-$pc_cntr.png';\\
set multiplot;\\
set datafile separator whitespace;\\
set title ' Progress $pc_3 ';\\
set xlabel 'Exam';\\
set ylabel 'Mean Score';\\
%;
	my @xtics = ();
	
	#to label the
	#y axis
	my ($min, $max);
	#and x axis
	my @exam_list = ();

	my %subject_scores = ();	

	my %subjects = ();
	my $subj_cntr = 0;
	my $exam_cntr = 0;

	my $current_year = "";

	for my $exam ( sort { $exam_seq{$a} <=> $exam_seq{$b} } keys %{$means{$pc_3}} ) {
		push @exam_list, $exam;
		if ( $exam =~ /(\d{4})/ ) {
			my $yr = $1;
			#add to xtics
			if ($yr ne $current_year) {
				push @xtics, qq%'$yr' $exam_cntr%;
				$current_year = $yr;
			}
			else {
				push @xtics, qq%'' $exam_cntr%;
			}
		}

		#push @xtics, qq%'$exam' $exam_cntr%;

		$subject_scores{$exam_cntr} = {};

		${$subject_scores{$exam_cntr}}{"Mean score"} = ${${$means{$pc_3}}{$exam}}{"mean"};
		my $rounded_mean = sprintf("%.0f", ${${$means{$pc_3}}{$exam}}{"mean"});

		if (not exists $subjects{"Mean score"}) {
			$subjects{"Mean score"} = $subj_cntr++;
		}

		#default min/max is the mean
		if (not defined $min) {
			$min = $rounded_mean;
			$max = $rounded_mean;
		}

		else {
			#decimals might be a problem, trim
			$min = $rounded_mean if ($rounded_mean < $min);
			$max = $rounded_mean if ($rounded_mean > $max);
		}

		for my $subject (keys %{${$means{$pc_3}}{$exam}}) {
			#avoid including 'count', 'sum_squares' etc
			next if (not ref(${${$means{$pc_3}}{$exam}}{$subject}) );
			next if (not exists ${${${$means{$pc_3}}{$exam}}{$subject}}{"mean"});	
			${$subject_scores{$exam_cntr}}{$subject} = ${${${$means{$pc_3}}{$exam}}{$subject}}{"mean"};

			if (not exists $subjects{$subject}) {
				$subjects{$subject} = $subj_cntr++;
			}

			my $rounded_mean = sprintf("%.0f",${${${$means{$pc_3}}{$exam}}{$subject}}{"mean"});
			$min = $rounded_mean if ($rounded_mean < $min);
			$max = $rounded_mean if ($rounded_mean > $max);
		}
		$exam_cntr++;
	}

	$subjects_per_pc{$pc_cntr} = \%subjects;
 
	my $set_x_tics = "";
	if (@xtics) {
		$set_x_tics = "set xtics (" . join(", ", @xtics) . ");\\";
	}

	$gnuplot_code .=

qq%set xrange [0:$#exam_list];\\
set yrange [$min:$max];\\
$set_x_tics
set ytics;\\
set grid ytics;\\
set grid xtics;\\
set tmargin at screen 0.9;\\
set bmargin at screen 0.1;\\
set rmargin at screen 0.98;\\
set lmargin at screen 0.15;\\
%;

	my @missing = ();	
	my $subject_plot = "";
	
	my $color_cntr = 0;		

	my $num_of_exams = scalar(@exam_list);
	my $exam_indeces_vector = "c(" . join(", ", 0..($num_of_exams - 1)) . ")";	

	for my $subj ( sort { $subjects{$a} <=> $subjects{$b} } keys %subjects ) {
		#init data to 0s
		my @data = ();
		for (my $i = 0; $i < $num_of_exams; $i++) {
			$data[$i] = 0;	
		}
		my $prev_exam = -1;
		for my $exam (sort {$a <=> $b} keys %subject_scores ) {

			for my $subj_2 (keys %{$subject_scores{$exam}}) {
				#reverse $subject_scores 
				next unless ($subj eq $subj_2);
				#$exam is a number, convenient as an index
				#may have fixed that missing values bug
				#this might be what was overwriting
				#my preset 0 val for all scores.
				my $score_val = ${$subject_scores{$exam}}{$subj};
		
				if (defined $score_val and $score_val =~ /^\d+(?:.\d+)*$/)  {
					$data[$exam] = $score_val;
				}

				#detect gap in @data
				if ($exam > 0) {
					if (not defined $data[$exam - 1]) {
						#cex, set min
						my $missing_index = $exam - 1;
						#$data[$exam - 1] = 0;

						$gnuplot_code .=

qq!set label '*' at first $missing_index,0;\\
!;
						push (@missing, $subj . " " . $exam_list[$exam - 1]);	
					}
				}
			}
		}

		for (my $i = 0; $i < @data; $i++) {
			$gnuplot_data .= qq%$i $data[$i]\n%;
		}

		$gnuplot_data .= "e\n";
		#$gnuplot_data .= "e\n";

		my $subjects_vector = "c(" . join(", ", @data) . ")"; 	

		$gnuplot_code .=
qq%plot '-' using 1:2 notitle with linespoints linecolor rgb '$color_palette[$color_cntr]' linewidth 3;\\
%;
			
		if ($color_cntr == 0) {
			$gnuplot_code .=
qq%unset ylabel;\\
unset xlabel;\\
unset ytics;\\
unset xtics;\\
unset title;\\
%;	
		}
		$color_cntr = 0 if (++$color_cntr >= scalar(@color_palette));
	}

	if (@missing) {
		$missings{$pc_cntr} = \@missing;
	}

	my $exam_list_vector = "c(\"" . join("\", \"", @exam_list) . "\")";

	$gnuplot_code .= 
qq%unset multiplot;\\
%;
  

	$pc_cntr++;
}


	`echo "$gnuplot_data" | gnuplot -e "$gnuplot_code"`;
	
	$pc_cntr = 0;
	for my $pc_3 ( sort {$a cmp $b} keys %means ) {
		if ( -e "${doc_root}/images/graphs/$file_name_prefix-$pc_cntr.png" ) {
			$graph .=
qq!
<p>
<hr style="height: 2px; color: black; background-color: black"><p><h3>$pc_3</h3>
<table border="1">
<td><a href="/images/graphs/$file_name_prefix-$pc_cntr.png"><img src="/images/graphs/$file_name_prefix-$pc_cntr.png" alt="$pc_3" title="$pc_3"></a>
<td style="vertical-align: middle">
!;
			#add legend
			#1st subjects
			my $color_cntr = 0;	
			for my $subj (sort { ${$subjects_per_pc{$pc_cntr}}{$a} <=>  ${$subjects_per_pc{$pc_cntr}}{$b} }  keys %{$subjects_per_pc{$pc_cntr}}) {
			
				my $color = $color_palette[$color_cntr];
				$graph .= qq!<span style="color: $color">$subj</span><br>!;
				$color_cntr = 0 if (++$color_cntr >= @color_palette);
			}
			#next missing subjects (if any)
			if ( exists $missings{$pc_cntr} ) {
				$graph .= "<em>* Data missing</em> (" . join(", ", @{$missings{$pc_cntr}}) . ")";
			}
			$graph .= "</table>";
		}
		else {
			print STDERR "Graph for $pc_3 was not created by R$/";
		}
		$pc_cntr++;	
	}
	$data_str .= $graph;
}

else {
$data_str .= qq!<hr style="height: 4px; color: black; background-color: black"><p><h2>Graphs</h2><span style="color: red">No progress graphs to display.</span> To see progress graphs, you must select more than 1 exam to analyze!;
}
}
	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
</head>
<body>
$header
<p><em>Dataset size: $dataset_size</em>&nbsp;(<a href="/cgi-bin/viewdataset.cgi" target="_blank">View Dataset</a>)
$data_str
</body></html>
*;

}
}
#cross tabulation
if ($session{"analysis_type"} eq "cross_tab") {

	my $data_str = "";

	my @missing_invalid = ();

	my ($field_1, $field_2) = (undef, undef);
	my $marks_at_adm_batch_size = 20; 

	#Atleast 1 because of _total
	my $field_2_uniques_count = 0;

	my %distribution;

	my %valid_field_names = ("club/society" => "Clubs/Societies", "responsibility" => "Responsibilities", "sport/game" => "Sports/Games", "class" => "Class", "dorm" => "Dorm", "marks at admission" => "Marks at Admission");		
	if (exists $auth_params{"field_1"}) {
		if (exists $valid_field_names{lc($auth_params{"field_1"})}) {
			$field_1 = $valid_field_names{lc($auth_params{"field_1"})};
			if ($field_1 eq "Marks at Admission") {
				if (exists $auth_params{"batch_1"} and $auth_params{"batch_1"} =~ /^\d+$/) {
					$marks_at_adm_batch_size = $auth_params{"batch_1"};
				}
			}
		}
		else {
			push @missing_invalid, "1<sup>st</sup> Field";
		} 
	}
	else {
		push @missing_invalid, "1<sup>st</sup> Field";
	}

	if (exists $auth_params{"field_1"}) {
		if (exists $valid_field_names{lc($auth_params{"field_2"})}) {
			$field_2 = $valid_field_names{lc($auth_params{"field_2"})};
			if ($field_2 eq "Marks at Admission") {
				if (exists $auth_params{"batch_2"} and $auth_params{"batch_2"} =~ /^\d+$/) {
					$marks_at_adm_batch_size = $auth_params{"batch_2"};
				}
			}
		}
		else {
			push @missing_invalid, "2<sup>nd</sup> Field";
		}
	}
	else {
		push @missing_invalid, "2<sup>nd</sup> Field";
	}
	
	if (@missing_invalid) {
		my $missing = join(", ", @missing_invalid);
		$data_str .= qq!<p><span style="color: red">Could not perform cross-tabulation due to the following missing or invalid inputs: $missing</span>!;
	}
	else {
		if ($field_1 eq $field_2) {
			$data_str .= qq!<p><span style="color: red">Did not perform cross-tabulation because Field 1 and Field 2 are the same.</span>!;
		}
		else {
			my %unique_field_2;
			foreach (keys %matching_adms) {
				my $field_1_val = "-";
				if ($field_1 eq "Marks at Admission") {
					if (${$matching_adms{$_}}{"Marks at Admission"} =~ /^(\d+)$/) {
						#presumably cheaper than another de-ref
						#premature optimazation?
						my $marks = $1;
						#say int(63 / 50) * 50 == 1 * 50 == 50 
						my $group_start = int($1 / $marks_at_adm_batch_size) * $marks_at_adm_batch_size;
						#say 50 . "-" . (50 + (50 - 1)) == "50-99"
						my $group = $group_start . "-" . ($group_start + ($marks_at_adm_batch_size - 1));
						$field_1_val = $group;
					}
				}
				else { 
					$field_1_val = ${$matching_adms{$_}}{$field_1};
				}

				my $field_2_val = "-";
				if ($field_2 eq "Marks at Admission") {
					if (${$matching_adms{$_}}{"Marks at Admission"} =~ /^(\d+)$/) {
						#presumably cheaper than another de-ref
						#premature optimazation?
						my $marks = $1;
						#say int(63 / 50) * 50 == 1 * 50 == 50 
						my $group_start = int($1 / $marks_at_adm_batch_size) * $marks_at_adm_batch_size;
						#say 50 . "-" . (50 + (50 - 1)) == "50-99"
						my $group = $group_start . "-" . ($group_start + ($marks_at_adm_batch_size - 1));
						$field_2_val = $group;
					}
				}
				else { 
					$field_2_val = ${$matching_adms{$_}}{$field_2};
				}

				if (not exists $unique_field_2{$field_2_val}) {	
					$field_2_uniques_count++;
				}
				$unique_field_2{$field_2_val}++;

				unless (exists $distribution{$field_1_val}) {
					$distribution{$field_1_val} = {"_total" => 0};
				}

				${$distribution{$field_1_val}}{$field_2_val}++;
				${$distribution{$field_1_val}}{"_total"}++;	
			}
			
			my @sorted_field_2 = sort { $unique_field_2{$b} <=> $unique_field_2{$a}} keys %unique_field_2;

			
			my $field_2_header = "<TH>" . join("<TH>", @sorted_field_2);
  			
			$data_str .= 
qq!
<TABLE border="1" cellpadding="10%">
<THEAD>

<TR>
<TH rowspan="2">$field_1
<TH colspan="$field_2_uniques_count">$field_2
<TH rowspan="2">Total

<TR>$field_2_header
</THEAD>
<TBODY>
!;
			my $total = 0;

			for my $field_1_value ( sort { ${$distribution{$b}}{"_total"} <=>  ${$distribution{$a}}{"_total"} } keys %distribution ) {
				$data_str .= qq!<TR><TD style="font-weight: bold">$field_1_value!;
				for my $field_2_value (@sorted_field_2) {
					if ( exists ${$distribution{$field_1_value}}{$field_2_value} ) {
						$data_str .= "<TD>${$distribution{$field_1_value}}{$field_2_value}";
					}
					else {
						$data_str .= "<TD>&nbsp;";
					}
				}
				$data_str .= qq!<TD>${$distribution{$field_1_value}}{"_total"}!;
				$total += ${$distribution{$field_1_value}}{"_total"};
			}

			$data_str .= qq!<TR style="font-weight: bold"><TD>All!;

			foreach (@sorted_field_2) {
				$data_str .= qq!<TD>$unique_field_2{$_}!;
			}
			$data_str .= "<TD>$total";	
			$data_str .=
qq!</TBODY>
</TABLE>
!;

		}
	}

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
</head>
<body>
$header
<p><em>Dataset size: $dataset_size</em>&nbsp;(<a href="/cgi-bin/viewdataset.cgi" target="_blank">View Dataset</a>)
$data_str
</body></html>
*;


}

#correlation analysis
elsif ($session{"analysis_type"} eq "correlation") {
	my $data_str = "";
	my $js = "";
	my $view_dataset = "";

	my @missing = ();

	my $corr_dataset_size = 0;

	#my ($f_class_1, $f_class_2);
	#my ($class_1, $class_1_yr, $class_2, $class_2_yr, $exam_1, $exam_2, $subject_1, $subject_2) = (undef,undef, undef, undef, undef, undef, undef, undef);
	my ($exam_1, $exam_2, $subject_1, $subject_2) = (undef,undef, undef, undef);

	#find out what data sets to analyze

	#Exam 1
	if (exists $auth_params{"val_1_exam"}) {
		$exam_1 = $auth_params{"val_1_exam"};
	}
	else {
		push @missing, "2<sup>nd</sup> Value/Exam";
	}

	#Exam 2
	if (exists $auth_params{"val_2_exam"}) {
		$exam_2 = $auth_params{"val_2_exam"};
	}
	else {
		push @missing, "2<sup>nd</sup> Value/Exam";
	}

	#Subject 1
	if (exists $auth_params{"val_1_subject"}) {
		$subject_1 = $auth_params{"val_1_subject"};
	}
	else {
		push @missing, "1<sup>st</sup> Value/Subject";
	}

	#Subject 2
	if (exists $auth_params{"val_2_subject"}) {
		$subject_2 = $auth_params{"val_2_subject"};
	}
	else {
		push @missing, "2<sup>nd</sup> Value/Subject";
	}

	if (@missing) {
		#multiple missing
		if (scalar(@missing) > 1) {
			my $missing_list = join(", ", @missing);	
			$data_str .= qq!<p><span style="color: red">Could not calculate correlation due to the following missing values: $missing_list</span>!;
		}
		#1 missing
		else {
			$data_str .= qq!<p><span style="color: red">Could not calculate correlation due to the following missing value: $missing[0]</span>!;
		}
	}
	else {
		#analysis on same values
		#if ( (lc($class_1) eq lc($class_2)) and (lc($exam_1) eq lc($exam_2)) and (lc($subject_1) eq lc($subject_2)) ) {
		if ( (lc($exam_1) eq lc($exam_2)) and (lc($subject_1) eq lc($subject_2)) ) {
			$data_str .= qq!<p><span style="color: red">Value 1 and Value 2 are the same. Performing this operation would give a correlation of 1(perfect positive correlation).</span>!;
		}
		else {
			my ($roll_1, $roll_2);
			my @marksheets_1 = ();
			my @marksheets_2 = ();

			
				for my $marksheet (keys %marksheets) {

					#my $roll = ${$marksheets{$marksheet}}{"roll"};
					my $exam = ${$marksheets{$marksheet}}{"exam_name"};
					my $subject = ${$marksheets{$marksheet}}{"subject"};

					
						#same exam?
						if ( lc($exam) eq lc($exam_1) ) {
							#if subject is 'Mean score' just add,
							if ( lc($subject_1) eq "mean score" ) {
								push @marksheets_1, $marksheet;
							}
							#otherwise add on eq .
							else {
								if (lc($subject_1) eq lc($subject)) {
									push @marksheets_1, $marksheet;
								}
							}
						}
				
					#Use if not elsif, user might be performing analysis
					#on the same class
					
						#same exam?
						if ( lc($exam) eq lc($exam_2) ) {
							#if subject is 'Mean score' just add,
							if ( lc($subject_2) eq "mean score" ) {
								push @marksheets_2, $marksheet;
							}
							#otherwise add on eq .
							else {
								if (lc($subject_2) eq lc($subject)) {
									push @marksheets_2, $marksheet;
								}
							}
						}
						
				}
				my %stud_scores;

				my ($val_1_is_multi, $val_2_is_multi) = (0,0);
				$val_1_is_multi = 1 if (scalar(@marksheets_1) > 1);
				$val_2_is_multi = 1 if (scalar(@marksheets_2) > 1);

				my $roll_1_matched = 0;
 
				for my $marksheet (@marksheets_1) {	
 					my $prep_stmt_3_4 = $con->prepare("SELECT adm,marks FROM `$marksheet`");	

					if ($prep_stmt_3_4) {
						my $rc = $prep_stmt_3_4->execute();
						if ($rc) {
							while (my @rslts = $prep_stmt_3_4->fetchrow_array()) {
								next unless (defined $rslts[0] and defined $rslts[1]);
								if (exists $matching_adms{$rslts[0]}) {
									$roll_1_matched++;
									#if analysing mean, calculate mean
									if ($val_1_is_multi) {
										if ( not exists $stud_scores{$rslts[0]} ) {
											$stud_scores{$rslts[0]} = {"x" => 0, "count" => 0};	
										}

										${$stud_scores{$rslts[0]}}{"count"}++;
										my $diff = $rslts[1] - ${$stud_scores{$rslts[0]}}{"x"};
										${$stud_scores{$rslts[0]}}{"x"} += ($diff / ${$stud_scores{$rslts[0]}}{"count"});
									}
									else {
										${$stud_scores{$rslts[0]}}{"x"} = $rslts[1];
									}
								}
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM $marksheet statement: ", $prep_stmt_3_4->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM $marksheet statement: ", $prep_stmt_3_4->errstr, $/;
					}
				}

				for my $marksheet_2 (@marksheets_2) {	
 					my $prep_stmt_3_4 = $con->prepare("SELECT adm,marks FROM `$marksheet_2`");

					if ($prep_stmt_3_4) {
						my $rc = $prep_stmt_3_4->execute();
						if ($rc) {
							while (my @rslts = $prep_stmt_3_4->fetchrow_array()) {
								#must already have an x-val
								next if (not exists $stud_scores{$rslts[0]});
								if (exists $matching_adms{$rslts[0]}) {
									#if analysing mean, calculate mean
									if ($val_2_is_multi) {
										if ( not exists ${$stud_scores{$rslts[0]}}{"y"} ) {
											${$stud_scores{$rslts[0]}}{"y"} = 0;
											${$stud_scores{$rslts[0]}}{"count"} = 0;
										}

										${$stud_scores{$rslts[0]}}{"count"}++;
										my $diff = $rslts[1] - ${$stud_scores{$rslts[0]}}{"y"};
										${$stud_scores{$rslts[0]}}{"y"} += ($diff / ${$stud_scores{$rslts[0]}}{"count"});
									}
									else {
										${$stud_scores{$rslts[0]}}{"y"} = $rslts[1];
									}
								}
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM $marksheet_2 statement: ", $prep_stmt_3_4->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM $marksheet_2 statement: ", $prep_stmt_3_4->errstr, $/;
					}
				}
				
				for my $adm (keys %stud_scores) {
					#delete x-vals with no corresponding y-val
					unless (exists ${$stud_scores{$adm}}{"x"} and exists ${$stud_scores{$adm}}{"y"}) {	
						delete $stud_scores{$adm};
					}
				}
				#I have a dataset I can use.
				$corr_dataset_size = scalar(keys %stud_scores);
		
				if ($corr_dataset_size > 0) {
					
					my ($x_sum, $x_mean);
					my ($y_sum, $y_mean);			
					my $count;

					my @cor_data_set_bts = ();
					
					my (@x_s, @y_s);

					foreach (keys %stud_scores) {
						$x_sum += ${$stud_scores{$_}}{"x"};
						push @x_s, ${$stud_scores{$_}}{"x"};

						$y_sum += ${$stud_scores{$_}}{"y"};
						push @y_s, ${$stud_scores{$_}}{"y"};

						$count++; 
						push @cor_data_set_bts, qq!$_: "${$matching_adms{$_}}{"Name"},${$stud_scores{$_}}{"x"},${$stud_scores{$_}}{"y"}"!;
					}

					$x_mean = $x_sum / $count;
					$y_mean = $y_sum / $count;

					my ($a_b_sum, $a_sq_sum, $b_sq_sum ) = (0, 0, 0);

					#correlation formula
					foreach (keys %stud_scores) {
						my $a_b = (${$stud_scores{$_}}{"x"} - $x_mean) * (${$stud_scores{$_}}{"y"} - $y_mean);
						$a_b_sum += $a_b;

						my $a_sq = (${$stud_scores{$_}}{"x"} - $x_mean) ** 2;
						$a_sq_sum += $a_sq;

						my $b_sq = (${$stud_scores{$_}}{"y"} - $y_mean) ** 2;
						$b_sq_sum += $b_sq;
					}

					my $cor = $a_b_sum / sqrt($a_sq_sum * $b_sq_sum);
	
					$data_str .= "<p><h4>Correlation: $cor</h4>";

					my $cor_data_set = "var cor_data = {" . join(", ", @cor_data_set_bts) . "}";
					
					#my $file_name = uc(sha1_hex(lc($class_1 . $class_2 . $class_1_yr . $class_2_yr . $exam_1 . $exam_2 . $subject_1 . $subject_2))). ".js";
					my $file_name = uc(sha1_hex(lc($exam_1 . $exam_2 . $subject_1 . $subject_2))). ".js";
					open(my $js_out, ">${doc_root}/js/$file_name") or print STDERR "Could not create js file: $!";

					if ($js_out) {
						print $js_out $cor_data_set or print STDERR "Could not write to js file: $!";
						$js .= 
qq!
<SCRIPT type="text/javascript" src="/js/$file_name"></SCRIPT>
<SCRIPT type="text/javascript">

function show() {
	var new_content = "<p><TABLE border=\\"1\\"><THEAD><TH>Adm no.<TH>Name<TH>$exam_1/$subject_1<TH>$exam_2/$subject_2</THEAD>";
	for (adm in cor_data) {
		var data = cor_data[adm].split(",");
		new_content += "<TR><TD><a href=\\"/cgi-bin/viewresults.cgi?adm=" + adm + "\\">" + adm + "</a>" + "<TD>" + data[0] + "<TD>" + data[1] + "<TD>" + data[2]; 
	}
	document.getElementById("dataset").innerHTML = new_content;
	document.getElementById("hide_show_dataset").innerHTML = "(<a href=\\"javascript:hide()\\">Hide Dataset</a>)";
}

function hide() {
	document.getElementById("dataset").innerHTML = "";
	document.getElementById("hide_show_dataset").innerHTML = "(<a href=\\"javascript:show()\\">Show Dataset</a>)";
}

</SCRIPT>
!;
						$view_dataset .= qq!&nbsp;<span id="hide_show_dataset">(<a href="javascript:show()">View Dataset</a>)</span>!;
					}
					#plot
					my $x_vector = "c(" . join(", ", @x_s) . ")";
					my $y_vector = "c(" . join(", ", @y_s) . ")";
					my $r_code =
qq!
png(filename="${doc_root}/images/graphs/$file_name.png", height=500, width=600);
plot($x_vector, $y_vector, pch=19, type="p",  xlab="$exam_1/$subject_1", ylab="$exam_2/$subject_2", main="Scattergram", col="black");
!;

					#throw away stdout,stderr
					open(my $rscript, "|Rscript 2>/dev/null 1>/dev/null --no-init-file --no-site-file --default-packages=base,graphics,grDevices -") or print STDERR "Could not open pipe to Rscript$/";
					#can open pipe?
					if ($rscript) {
						print $rscript $r_code;
						#learnt that if I don't do close() on
						#FHs, sometimes no disk write happens
						#(non-blocking I/O.)
						close $rscript;
	
						#graph has been created?
						if ( -e "${doc_root}/images/graphs/$file_name.png" ) {
							$data_str .=
qq!
<h4>Scattergram</h4>
<p><a href="/images/graphs/$file_name.png"><img style="border: solid 2px" src="/images/graphs/$file_name.png" alt="Scattergram" title="Scattergram for $exam_1/$subject_1 against $exam_2/$subject_2"></a>

!;
						}
						else {
							print STDERR "Scattergram was not created by R$/";
						}
					}	
				}
				#I don't... 
				else {
					#1.) ...because there were values in Field 1 with no
					#matching values in Field 2
					if ($roll_1_matched) {
						$data_str .= qq!<p><span style="color: red">Could not calculate correlation because the figures provided in 'Value 1' have no corresponding values in 'Value 2'. </span>!;
					}
					#2.) ...because there was no matching records at-all
					else {
						$data_str .= qq!<p><span style="color: red">None of the records requested for the correlation analysis match those specified in the 'limit by' criteria.</span>!;
					}
				}	

		}
	}
		
	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
$js
</head>
<body>
$header
<p><em>Dataset size: $corr_dataset_size$view_dataset</em>
<span id="dataset"></span>
$data_str
</body></html>
*;
}
}
					#Fail- No matching students
					else {
						$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
</head>
<body>
$header
<em>None of the students match the conditions specified.</em>
</body>
</html>
*;
					}
				}
				#Early fail- no corresponding marksheets
				else {
					$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
</head>
<body>
$header
<em>There are no marksheets fitting the conditions you specified.</em>
</body>
</html>
*;
				}
			}
			#Early fail- no corresponding marksheets
			else {
				$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
</head>
<body>
$header
<em>There are no marksheets associated with the class/es you selected.</em>
</body>
</html>
*;
			}	
		}
		#Early fail- no such class/es
		else {
			my $error_msg = "<em>There are no classes created in the system.</em>";
			if (exists $session{"classes"}) {
				$error_msg = "<em>None of the classes you selected exists in the system.</em>";
			}

			$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
</head>
<body>
$header
$error_msg
</body>
</html>
*;
		}
	}
}

L: {
if ($stage == 2) {	
	$update_session++;
	my $analysis_type = "";
	#persist new analysis preferences 
	#analysis_type
	if (exists $auth_params{"analysis_type"}) {
		$analysis_type = $auth_params{"analysis_type"};
		if ( ($analysis_type eq "group_by") or ($analysis_type eq "correlation") or ($analysis_type eq "cross_tab") ) {
			$session{"analysis_type"} = $analysis_type; 
		}
		else {
			push @errors, "Invalid analysis type selected. Supported analysis are: group-by, cross-tabulation and correlation";
		}
	}
	else {
		push @errors, "No analysis type specified. Supported analysis are: group-by, cross-tabulations and correlation."
	}
	
	my (@clubs_societies, @responsibilities, @subjects, @sports_games, @classes, @exams, @dorms, $marks_at_adm);
	my ($dataset, @dataset_bts) = ("", ());

	for my $auth_param (keys %auth_params) {
		#Clubs/Societies
		if ($auth_param =~ m!Clubs/Societies_(.+)! and $auth_params{$auth_param} == 1) {
			push @clubs_societies, $1;	
		}
		#Responsibilities
		elsif ($auth_param =~ m!Responsibilities_(.+)! and $auth_params{$auth_param} == 1) {
			push @responsibilities, $1;	
		}
		#Subjects
		elsif ($auth_param =~ m!Subject_(.+)! and $auth_params{$auth_param} == 1) {
			push @subjects, $1;	
		}
		#Sports/Games
		elsif ($auth_param =~ m!Sports/Games_(.+)! and $auth_params{$auth_param} == 1) {
			push @sports_games, $1;	
		}
		#Classes
		elsif ($auth_param =~ m!Class_(.+)! and $auth_params{$auth_param} == 1) {
			my $class = $1;
			if (exists $auth_params{$auth_param . "_grad_year"} and $auth_params{$auth_param . "_grad_year"} =~ /^(\d+)$/) {
				my $grad_yr = $1;
				push @classes, qq!$class($grad_yr)!;
			}
			else {
				push @errors, "A Class name was provided without a graduation year.";
			}
		}
		#Exams
		elsif ($auth_param =~ m!Exam_(.+)! and $auth_params{$auth_param} == 1) {
			push @exams, $1;
			
		}
		#Dorms
		elsif ($auth_param =~ m!Dorm_(.+)! and $auth_params{$auth_param} == 1) {
			push @dorms, $1;
		}
		#Marks at Admission
		elsif ($auth_param eq "Marks at Admission_lim_value") {
			if ($auth_params{"Marks at Admission_lim_value"} ne "") {
				if ($auth_params{"Marks at Admission_lim_value"} =~ /^(\d+)$/) {
					my $marks_at_admission = $1;
					if (exists $auth_params{"Marks at Admission_lim_type"}) {
						my $lim_type = $auth_params{"Marks at Admission_lim_type"};
						if ($lim_type eq "gt" ) {
							$marks_at_adm = ">$marks_at_admission";
							push @dataset_bts, "Marks at admission($marks_at_adm)";
						}
						elsif ($lim_type eq "lt") {
							$marks_at_adm = "<$marks_at_admission";
							push @dataset_bts, "Marks at admission($marks_at_adm)";
						}
						else {
							push @errors, "Marks at admission passed in with an invalid limit type. Valid values for the limit type are Greater than or Less than.";	
						}
					}
					else {
						push @errors, "Marks at admission passed in without a limit type(Greater than or Less than).";	
					}
				}
				else {
					push @errors, "Invalid marks at admission. This value should be a number.";	
				}
			}
		}
	}	

	#Clubs/Societies
	if (@clubs_societies) {
		$session{"clubs_societies"} = join(",", @clubs_societies);
		push @dataset_bts, "Clubs/Societies(" . $session{"clubs_societies"} . ")";
	}
	#Responsibilities
	if (@responsibilities) {
		$session{"responsibilities"} = join(",", @responsibilities);
		push @dataset_bts, "Responsibilities(" .$session{"responsibilities"} . ")";	
	}
	#Subjects
	if (@subjects) {
		$session{"subjects"} = join(",", @subjects);
		push @dataset_bts, "Subjects(" . $session{"subjects"} . ")";	
	}
	#Sports/Games
	if (@sports_games) {
		$session{"sports_games"} = join(",", @sports_games);
		push @dataset_bts, "Sports/Games(" . $session{"sports_games"} . ")";	
	}
	#Classes
	if (@classes) {
		$session{"classes"} = join(",", @classes);
		push @dataset_bts, "Classes[" . $session{"classes"} . "]";	
	}
	#Exams
	if (@exams) {
		$session{"exams"} = join(",", @exams);
		push @dataset_bts, "Exams(" . $session{"exams"} . ")";	
	}
	#Dorms
	if (@dorms) {
		$session{"dorms"} = join(",", @dorms);
		push @dataset_bts, "Dorms(" . $session{"dorms"} . ")";	
	}
	#Marks at Admission
	if (defined $marks_at_adm) {
		$session{"marks_at_adm"} = $marks_at_adm;	
	}
	#deal with errors
	#essentially, resend the user to the analysis.cgi 
	#page with an appropriate warning message
	if (@errors) {
		$stage = 1;
		last L;
	}

	if (@dataset_bts) {
		$dataset = "<p><em>Dataset: " . join(", ", @dataset_bts) . "</em>";
	}
	else {
		$dataset = "<p><em>Dataset: entire school</em>";
	}

	my $anal_spec_data = "";
	my $js = "";

#Group by analysis	
if ($analysis_type eq "group_by") {
	$anal_spec_data .=
qq!
<p>
<form action="/cgi-bin/analysis.cgi" method="POST">
<table>
<tr>
<td><label>Group by: </label>
<td>
<select name="group_by" id="group_by" onchange="extend_opts()">

<option value="Clubs/Societies">Club/Society</option>
<option value="Responsibilities">Responsibility</option>
<option value="Sports/Games">Sport/Game</option>
<option selected value="Class">Class</option>
<option value="Dorm">Dorm</option>
<option value="Marks at Admission">Marks at Admission</option>

</select>
</tr>
<tr><td colspan="2"><span id="marks_at_adm"></span></tr>
<tr>
<td>Analysis Scope
<td>
<ul style="list-style-type: none">

<li><input type="checkbox" name="scope_averages" checked>&nbsp;<label for="scope_averages">Averages and Standard Deviations</label>

<li><input type="checkbox" name="scope_grades">&nbsp;<label for="scope_grades">Distribution of Grades</label>
 
<li><input type="checkbox" name="scope_top" id="scope_top" onclick=extend("scope_top")>&nbsp;<label for="scope_top">Top Students</label>
<span id="scope_top_extend"></span>

<li><input type="checkbox" name="scope_bottom" id="scope_bottom" onclick=extend("scope_bottom")>&nbsp;<label for="scope_top">Bottom Students</label>
<span id="scope_bottom_extend"></span>

<li><input type="checkbox" name="scope_improved" id="scope_improved" onclick=extend("scope_improved")>&nbsp;<label for="scope_improved">Most Improved Students</label>
<span id="scope_improved_extend"></span>

<li><input type="checkbox" name="scope_declined" id="scope_declined" onclick=extend("scope_declined")>&nbsp;<label for="scope_declined">Most Declined Students</label>
<span id="scope_declined_extend"></span>

<li><input type="checkbox" name="scope_graphs">&nbsp;<label for="scope_graphs">Progress Graphs</label>

</ul>
</tr>
<tr>
<td><input type="submit" value="Run analysis">
<td>
</tr>
</table>
</form>
!;
		$js = 
qq*
<script>
var opts = '<label>In batches of: </label>&nbsp;<select name="batches"><option value="20">20 marks</option><option value="50">50 marks</option><option value="100">100 marks</option></select>';

var extensions = 
{"scope_top" : '<ul style="list-style-type: none"><li><label for="top_limit">Top</label>&nbsp;<select name="top_limit"><option value="3">3 students</option><option value="5">5 students</option><option value="10">10 students</option><option value="20">20 students</option></select></ul>',

"scope_bottom" : '<ul style="list-style-type: none"><li><label for="bottom_limit">Bottom</label>&nbsp;<select name="bottom_limit"><option value="3">3 students</option><option value="5">5 students</option><option value="10">10 students</option><option value="20">20 students</option></select></ul>',

"scope_improved" : '<ul style="list-style-type: none"><li><label for="improved_limit">Most Improved</label>&nbsp;<select name="improved_limit"><option value="3">3 students</option><option value="5">5 students</option><option value="10">10 students</option><option value="20">20 students</option></select></ul>',

"scope_declined" : '<ul style="list-style-type: none"><li><label for="declined_limit">Most Declined</label>&nbsp;<select name="declined_limit"><option value="3">3 students</option><option value="5">5 students</option><option value="10">10 students</option><option value="20">20 students</option></select></ul>',
};

function extend_opts() {
	var selection = document.getElementById("group_by").value;
	if (selection === "Marks at Admission") {
		document.getElementById("marks_at_adm").innerHTML = opts;
	}
	else {
		document.getElementById("marks_at_adm").innerHTML = "";
	}
}

function extend(checkbox) {
	if (document.getElementById(checkbox).checked == true) {
		document.getElementById(checkbox + "_extend").innerHTML = extensions[checkbox]; 
	}
	else {
		document.getElementById(checkbox + "_extend").innerHTML = "";
	}
}

</script>
*;
}
elsif ($analysis_type eq "cross_tab") {
	$anal_spec_data .=
qq!
<form method="POST" action="/cgi-bin/analysis.cgi">
<table border="1" cellpadding="10%">
<thead><th>1<sup>st</sup> Field<th>2<sup>nd</sup> Field</thead>
<tbody>
<tr>

<td>
<SELECT name="field_1" id="field_1" onchange="extend_opts(1)">

<OPTION value="Club/Society">Club/Society</OPTION>
<OPTION value="Responsibility">Responsibility</OPTION>
<OPTION value="Sport/Game">Sport/Game</OPTION>
<OPTION value="Class">Class</OPTION>
<OPTION value="Dorm" selected>Dorm</OPTION>
<OPTION value="Marks at Admission">Marks at Admission</OPTION>

</SELECT>
<br><span id="marks_at_adm_1"></span>

<td>
<SELECT name="field_2" id="field_2" onchange="extend_opts(2)">

<OPTION value="Club/Society">Club/Society</OPTION>
<OPTION value="Responsibility">Responsibility</OPTION>
<OPTION value="Sport/Game">Sport/Game</OPTION>
<OPTION value="Class" selected>Class</OPTION>
<OPTION value="Dorm">Dorm</OPTION>
<OPTION value="Marks at Admission">Marks at Admission</OPTION>

</SELECT>
<br><span id="marks_at_adm_2"></span>
</tbody>
</table>
<p><input type="submit" name="Run Analysis" value="Run Analysis">
</form>
!;

$js = 
qq!

<SCRIPT type="text/javascript">

var opts_1 = '<label>In batches of: </label>&nbsp;<select name="batches_1"><option value="20">20 marks</option><option value="50">50 marks</option><option value="100">100 marks</option></select>';

var opts_2 = '<label>In batches of: </label>&nbsp;<select name="batches_2"><option value="20">20 marks</option><option value="50">50 marks</option><option value="100">100 marks</option></select>';

function extend_opts(which) {
	if (which \!= 1 && which \!= 2) {
		return 0;
	}
	var selection = document.getElementById("field_" + which).value;
	if (selection === "Marks at Admission") {
		if (which == 1) {
			document.getElementById("marks_at_adm_1").innerHTML = opts_1;
		}
		else {
			document.getElementById("marks_at_adm_2").innerHTML = opts_2;
		}
	}
	else {
		document.getElementById("marks_at_adm_" + which).innerHTML = "";
	}
}
</SCRIPT>
!;
}

elsif ($analysis_type eq "correlation") {
	$anal_spec_data .=
qq!
<form method="POST" action="/cgi-bin/analysis.cgi">
<table border="1" cellpadding="10%">
<tr>
<td style="border-bottom-style: dotted; font-weight: bold">1<sup>st</sup> Value(x)<td style="border-bottom-style: dotted; font-weight: bold">2<sup>nd</sup> Value(y)
!;

#my $class_select = "";
my $exam_select = "";
my $subj_select = "";


my @vars_query_fields = ();
#subject limited
unless (exists $session{"subjects"}) {
	push @vars_query_fields, "1-subjects";
}
my @classes;
my $yrs_of_study;

#do a DB query for classes and/or subjects
if (@vars_query_fields) {
	my @query_bts = ();
	foreach (@vars_query_fields) {
		push @query_bts, "id=?";
	}

	my $query = join(" OR ", @query_bts);

	my $prep_stmt_2_0 = $con->prepare("SELECT id,value FROM vars WHERE $query LIMIT " .scalar(@vars_query_fields));

	if ($prep_stmt_2_0) {
		my $rc = $prep_stmt_2_0->execute(@vars_query_fields);
		if ($rc) {
			while (my @rslts = $prep_stmt_2_0->fetchrow_array()) {

				if ($rslts[0] eq "1-subjects") {
					my @subjects = ("Mean score");
					push @subjects, split/,/, $rslts[1];
					$subj_select .= qq!<LABEL for="val_1_subject">Subject</LABEL>&nbsp;&nbsp;<SELECT name="val_1_subject">!;
					for my $subject (sort {$a cmp $b} @subjects) {
						#by default use the mean score
						if ($subject eq "Mean score") {
							$subj_select .= qq!<OPTION selected value="$subject">$subject</OPTION>!;
						}
						else {
							$subj_select .= qq!<OPTION value="$subject">$subject</OPTION>!;
						}
					}
					$subj_select .= "</SELECT>";
				}
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM vars statement: ", $prep_stmt_2_0->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt_2_0->errstr, $/;
	}

}

#Subject limited
if (not defined $vars_query_fields[0]) {
	my @subjects = ("Mean score");
	push @subjects, split(/,/, $session{"subjects"});
	
	$subj_select .= qq!<LABEL for="val_1_subject">Subject</LABEL>&nbsp;&nbsp;<SELECT name="val_1_subject">!;
	foreach (@subjects) {
		$subj_select .= qq!<OPTION value="$_">$_</OPTION>!;
	}
}

#exam limit
if (exists $session{"exams"}) {
	my @exams = split/,/, $session{"exams"};
	if (scalar(@exams) > 1) {
		$exam_select .= qq!<LABEL for="val_1_exam">Exam</LABEL>&nbsp;&nbsp;<SELECT name="val_1_exam">!;
		foreach (@exams) {
			$exam_select .= qq!<OPTION value="$_">$_</OPTION>!;
		}
		$exam_select .= qq!</SELECT>!;
	}
	else {
		$exam_select .= qq!<LABEL for="val_1_exam">Exam</LABEL>&nbsp;&nbsp;<INPUT type="text" readonly name="val_1_exam" value="$exams[0]">!;
	}
}

else {
	$exam_select .= qq!<LABEL for="val_1_exam">Exam</LABEL>&nbsp;&nbsp;<SELECT name="val_1_exam">!;

	my $prep_stmt_2_2 = $con->prepare("SELECT DISTINCT exam_name FROM marksheets");
	
	if ($prep_stmt_2_2) {
		my $rc = $prep_stmt_2_2->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt_2_2->fetchrow_array()) {
				$exam_select .= qq!<OPTION value="$rslts[0]">$rslts[0]</OPTION>!;
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM marksheets statement: ", $prep_stmt_2_2->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt_2_2->errstr, $/;
	}

	$exam_select .= "</SELECT>";
}

#$anal_spec_data .= "<tr><td>$class_select";
#$class_select =~ s/val_1_class/val_2_class/g;
#$anal_spec_data .= "<td>$class_select";

$anal_spec_data .= "<tr><td>$exam_select";
$exam_select =~ s/val_1_exam/val_2_exam/g;
$anal_spec_data .= "<td>$exam_select";

$anal_spec_data .= "<tr><td>$subj_select";
$subj_select =~ s/val_1_subject/val_2_subject/g;
$anal_spec_data .= "<td>$subj_select";

$anal_spec_data .= qq!</table><p><input type="submit" name="Run Analysis" value="Run Analysis"></form>!;

}
	$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
$js
</head>
<body>
$header
$dataset
$anal_spec_data
</body>
</html>
*;
	$update_session++;
	$session{"stage"} = 3;
}
}

#Ask user what sought of analysis & on what
if ($stage == 1) {
	#reset old preferences	
	@session{"analysis_type", "analysis_id", "clubs_societies", "responsibilities", "sports_games", "classes", "exams", "subjects", "dorms", "marks_at_adm"} = ("", "", "", "", "", "", "", "", "", "");
	$update_session++;
	my %opts = ();
	my $yrs_of_study = 4;
	my $prep_stmt_1_0 = $con->prepare("SELECT id,value FROM vars WHERE id='1-classes' OR id='1-subjects' OR id='1-dorms' LIMIT 3");

	if ($prep_stmt_1_0) {
		my $rc = $prep_stmt_1_0->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt_1_0->fetchrow_array()) {
				if ($rslts[0] eq "1-classes") {
					my @classes = split/,/, $rslts[1];
					$opts{"Class"} = \@classes;
					if (@classes > 1) {
						my $yr = 1;
						my ($oldest,$youngest);
						if ($classes[0] =~ /(\d+)/) {
							$yr = $1;
							($oldest,$youngest) = ($yr, $yr);
						}
						
						for (my $i = 1; $i < @classes; $i++) {
							$yr = 1;
							if ($classes[$i] =~ /(\d+)/) {
								$yr = $1;
							}
							
							if ($yr < $youngest) {
								$youngest = $yr;
							}
							elsif ($yr > $oldest) {
								$oldest = $yr;
							}
						}
						$yrs_of_study = ($oldest - $youngest) + 1; 
					}
				}
				elsif ($rslts[0] eq "1-subjects") {
					my @subjects = split/,/, $rslts[1];
					$opts{"Subject"} = \@subjects;
				}
				elsif ($rslts[0] eq "1-dorms") {
					my @dorms = split/,/, $rslts[1];
					$opts{"Dorm"} = \@dorms;
				}
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM vars statement: ", $prep_stmt_1_0->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt_1_0->errstr, $/;
	}

	#What stud rolls are there
	my @student_rolls = ();

	my ($latest_grad_yr, $soonest_grad_yr) = (undef, undef);
	my $prep_stmt_1_1 = $con->prepare("SELECT table_name,grad_year FROM student_rolls");

	if ($prep_stmt_1_1) {
		my $rc = $prep_stmt_1_1->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt_1_1->fetchrow_array()) {
				push @student_rolls, $rslts[0];
				if (not defined $latest_grad_yr) {
					$latest_grad_yr = $rslts[1];
					$soonest_grad_yr = $rslts[1];
				}
				else {
					$soonest_grad_yr = $rslts[1] if ($rslts[1] < $soonest_grad_yr);
					$latest_grad_yr = $rslts[1] if ($rslts[1] > $latest_grad_yr);
				}
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt_1_1->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt_1_1->errstr, $/;
	}
	
	#Add Clubs/Sports/Responsibilities
	my (%clubs_societies, %sports_games, %responsibilities) = ((), (), ());

	for my $roll (@student_rolls) {
		my $prep_stmt_1_2 = $con->prepare("SELECT clubs_societies,sports_games,responsibilities FROM `$roll`");

		if ($prep_stmt_1_2) {
			my $rc = $prep_stmt_1_2->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt_1_2->fetchrow_array()) {
					my ($club, $sport, $respo) = @rslts;
					
					$club = "None" if (not defined $club);
					$sport = "None" if (not defined $sport);
					$respo = "None" if (not defined $respo);

					my @clubs = split /,/, $club;
					my @sports = split /,/, $sport;
					my @respons = split /,/, $respo;

					@clubs_societies{@clubs}++ if (@clubs);
					@sports_games{@sports}++ if (@sports);
					@responsibilities{@respons}++ if (@respons);
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM $roll statement: ", $prep_stmt_1_2->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt_1_2->errstr, $/;
		}
	}

	@opts{("Clubs/Societies", "Sports/Games", "Responsibilities")} = ([keys %clubs_societies], [keys %sports_games], [keys %responsibilities]);

	#Add exam
	#Read marksheets table

	my @exams = ();
	my $prep_stmt_1_3 = $con->prepare("SELECT DISTINCT exam_name FROM marksheets");

	if ($prep_stmt_1_3) {
		my $rc = $prep_stmt_1_3->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt_1_3->fetchrow_array()) {
				push @exams, $rslts[0];	
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM marksheets statement: ", $prep_stmt_1_3->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt_1_3->errstr, $/;
	}
	 
	$opts{"Exam"} = \@exams;

	my $expandable_sect = "";
	my $current_yr = (localtime)[5] + 1900;
	for my $category (keys %opts) {
		$expandable_sect .=
qq!
<p><span style="float: left; font-weight: bold">$category</span>&nbsp;<span id="expand_$category"><img border="1" style="height: 1em" src="/images/down.ico" title="Click to view options" onclick="expand('$category')"></span>
<div style="display: none" id="$category">
<table>
!
;
		for my $category_data (@{$opts{$category}}) {
			if ($category eq "Class") {
				my %grad_years = ();
				@grad_years{$soonest_grad_yr..$latest_grad_yr} = ($soonest_grad_yr..$latest_grad_yr);
				#stupid variable name
				#how do you say 'the graduating year
				#of the current bunch inhabiting the given class' 
				my $presumed_grad_yr = $current_yr;
				if ($category_data =~ /(\d+)/) {
					my $yr = $1;
					$presumed_grad_yr = $current_yr + ($yrs_of_study - $yr);	
				}
				$grad_years{$presumed_grad_yr}++;

				my $grad_yr_select = qq!<SELECT name="${category}_${category_data}_grad_year">!;
				foreach (keys %grad_years) {
					#set the 'presumed' grad year as selected
					if ($_ == $presumed_grad_yr) {
						$grad_yr_select .= qq!<OPTION selected value="$_">$_</OPTION>!;
					}
					else {
						$grad_yr_select .= qq!<OPTION value="$_">$_</OPTION>!;
					}
				}

				$grad_yr_select .= "</SELECT>";
				$expandable_sect .= qq!<tr><td><input type="checkbox" name="${category}_$category_data" value="1"><td>$category_data&nbsp;&nbsp;$grad_yr_select!;
			}
			else {
				$expandable_sect .= qq!<tr><td><input type="checkbox" name="${category}_$category_data" value="1"><td>$category_data!;
			}
		}

		$expandable_sect .= "</table></div>"
	}

	#Marks at Admission is treated specially
	#>|<|= x
	$expandable_sect .=
qq!
<p><span style="float: left; font-weight: bold">Marks at Admission</span>&nbsp;<span id="expand_Marks at Admission"><img border="1" style="height: 1em" src="/images/down.ico" title="Click to view options" onclick="expand('Marks at Admission')"></span>
<div style="display: none" id="Marks at Admission">
<table>
<tr><td><select name="Marks at Admission_lim_type">
<option value="gt">Greater than</option>
<option value="lt">Less than</option>
</select>
<td><input type="text" name="Marks at Admission_lim_value" value="" size="15" maxlength="5">
</table>
</div>
!; 	
	my @expandeds_js_hash_bts = ();

	push @expandeds_js_hash_bts, qq!"Marks at Admission": false!;
	for my $category_2 (keys %opts) {
		push @expandeds_js_hash_bts, qq!"$category_2": false!;
	}

	my $expandeds_js_hash .= qq!var expandeds = {};!;

	if (@expandeds_js_hash_bts) {
		$expandeds_js_hash = "var expandeds = {" . join(", ", @expandeds_js_hash_bts) . "};"; 
	}
	my $feedback = "";
	if (@errors) {
		$feedback .= qq!<span style="color: red">Some issues were observed with the data you sent over.</span><ol>!;
		foreach (@errors) {
			$feedback .= "<li>$_";
		}
		$feedback .= "</ol>";
	}

	$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
<script>
$expandeds_js_hash
function expand(category) {
	if (expandeds[category]) {
		document.getElementById("expand_" + category).innerHTML = '<img style="height: 1em" border="1" src="/images/down.ico" title="Click to view options" onclick="expand(\\'' + category + '\\')">';		
		document.getElementById(category).style.display = "none";
		expandeds[category] = false;
	}
	else {
		document.getElementById("expand_" + category).innerHTML = '<img style="height: 1em" border="1" src="/images/up.ico" title="Click to hide options" onclick="expand(\\''+ category + '\\')">';	
		document.getElementById(category).style.display = "inline";
		expandeds[category] = true;
	}
}

</script>

</head>
<body>
$header

<form action="/cgi-bin/analysis.cgi" method="POST">

<p><table>
<tr>
<td><label><em>What sort of analysis would you like to perform?</em></label>
<td><select name="analysis_type">
<option value="group_by">Group-by Analysis</option>
<option value="cross_tab">Cross-tabulation</option>
<option value="correlation">Correlation Analysis</option>
</select>
</table>

<div>
<p><em>Limit the dataset to analyse by the following criteria</em>
$expandable_sect
</div>

<p><input type="submit" name="start" value="Start Analysis">
</form>
</body>
</html>
*;
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

if ($update_session) { 
	my @new_sess_array = ();
	for my $sess_key (keys %session) {	
		push @new_sess_array, $sess_key."=".$session{$sess_key};        
	}
	my $new_sess = join ('&',@new_sess_array);
	print "X-Update-Session: $new_sess\r\n";
}

print "\r\n";
print $content;
$con->disconnect();

#usage do_add(tyref, key, value, desc, num);
sub do_add {
	return unless (@_ == 5);

	my ($k, $v) = ($_[1], $_[2]);
	my $bound = $_[4];
	$_[0]->{$k} = $v;

	my $delete = 0;
	my $cntr = 0;
	my $prev_mark = undef;
	
	my @sorted = ();

	if ($_[3] == 1) {
		@sorted = sort { $_[0]->{$b} <=> $_[0]->{$a} } keys %{$_[0]}
	}
	elsif($_[3] == 0) {
		@sorted = sort { $_[0]->{$a} <=> $_[0]->{$b} } keys %{$_[0]}
	}
	for my $best (@sorted) {	
		#in delete mode, del & move on
		if ($delete) {
			delete $_[0]->{$best};
			next;
		}
		#do an increment
		$cntr++;
		my $mark = $_[0]->{$best};	
		if (not defined $prev_mark or $mark != $prev_mark) {
			#del & enter del mode
			#new mark after u've seen enough
			if ($cntr > $bound) {
				delete $_[0]->{$best};
				$delete++;
			}
			else {
				$prev_mark = $mark;
			}
		}
	}
}

#usage return_ordered(ref, desc) 
sub return_ordered {	
	return unless (@_ == 2);

	my $ordered = "";
	my @sorted = ();

	#get top
	if ($_[1] == 1) {
		@sorted = sort { $_[0]->{$b} <=> $_[0]->{$a} } keys %{$_[0]}
	}
	#get bottom
	elsif ($_[1] == 0) {
		@sorted = sort { $_[0]->{$a} <=> $_[0]->{$b} } keys %{$_[0]}
	}

	my $posi = 0;
	my $prev_mark = undef;
	my $cntr = 0;
	foreach (@sorted) {
		my $mark = $_[0]->{$_};
		$cntr++;
		if (not defined $prev_mark or $mark != $prev_mark) {
			$posi = $cntr;
			$prev_mark = $mark;
		}
		#Need to re-scope %matching_adms & group_by
		my $name = ${$matching_adms{$_}}{"Name"};
		my $class = "";
		unless ($group_by eq "Class") {
			$class .= ", " . ${$matching_adms{$_}}{"Class"};
		}
		$ordered .= qq!<br>$posi.) <a href="/cgi-bin/viewresults.cgi?adm=$_">$_</a> ($name$class); $mark<br>!;
	}
	return $ordered;
}

sub get_grade {
	my $grade = "";
	return "" unless (@_);
	my $score = $_[0];
	#allow decimal grades?
	return "" unless ($score =~ /^\d+(\.\d+)?$/);

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

sub return_ordered_grades {
	return unless (@_ == 1);
	my $ordered = "";

	my @ordered = sort sort_grades keys %{$_[0]};	
	for (my $i = 0; $i < @ordered; $i++) {
		$ordered .= sprintf("%-2s: %3d", $ordered[$i], ${$_[0]}{$ordered[$i]}) . "<br>";
	}
	return $ordered;
}

sub sort_grades {
	#has +/-	
	my ($signed, $a_main, $b_main, $a_sign, $b_sign) = (0, "", "", "_", "_");
	if ($a =~ /^([A-Z])([\+\-])$/) {
		$a_main = $1;
		$a_sign = $2;
		$signed++;	
	}
	else {
		$a_main = $a; 
	}

	if ($b =~ /^([A-Z])([\+\-])$/) {
		$b_main = $1;
		$b_sign = $2;
		$signed++;	
	}
	else {
		$b_main = $b; 
	}

	if ($signed) {
		if ($a_main eq $b_main) {
			$sign_strength{$a_sign} <=> $sign_strength{$b_sign};
		}
		else {
			$a_main cmp $b_main;
		}
	}
	else {
		return $a cmp $b;
	}
}

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

#was running into issues because
#classes are proc'd sequentially i.e.
#each class' marksheets are cleared before
#proceeding to the next class. This has the effect
#of finding the mixing final and intermediate mean(from 
#the Knuth shortcut) together; screwing up the calculation
#of overall_xxx.
sub marksheet_sort {
	my $cmp = $exam_seq{${$marksheets{$a}}{"exam_name"}} <=> $exam_seq{${$marksheets{$b}}{"exam_name"}};

	if ($cmp == 0) {
		#marksheets from the same time & roll are unequal
		#marksheets from the same time but diff rolls are equal
		#should allow a nice mix of rolls.
		if (${$marksheets{$a}}{"roll"}	eq ${$marksheets{$b}}{"roll"}) {
			$cmp = 1;
		}
	}
	return $cmp;
}
